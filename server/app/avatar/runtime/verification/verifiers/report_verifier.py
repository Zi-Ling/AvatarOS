"""
ReportDeliverableVerifier — three-check verifier for report-type subtask outputs.

Checks:
  1. file_exists   — file is present on disk
  2. markdown_nonempty — file has meaningful content (above min size threshold)
  3. topic_coverage — file text contains expected topic keywords

All thresholds come from ReportVerifierConfig (dataclass, no hardcoding).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, FrozenSet, List, Optional

from app.avatar.runtime.verification.models import (
    VerificationStatus,
    VerifierConditionType,
    VerifierSpec,
)
from app.avatar.runtime.verification.verifiers.base import BaseVerifier

if TYPE_CHECKING:
    from app.avatar.runtime.verification.models import VerificationResult, VerificationTarget
    from app.avatar.runtime.workspace.session_workspace import SessionWorkspace

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReportVerifierConfig:
    """Tunable parameters for ReportDeliverableVerifier."""

    # Minimum file size in bytes to consider non-empty
    min_file_size_bytes: int = 50
    # Extensions treated as text-readable reports
    text_report_extensions: FrozenSet[str] = frozenset({
        "md", "txt", "html", "rst", "adoc", "tex",
    })
    # Minimum fraction of topic keywords that must appear (0.0–1.0)
    topic_coverage_threshold: float = 0.3
    # Max bytes to read for topic scanning (avoid reading huge files fully)
    topic_scan_max_bytes: int = 512_000


class ReportDeliverableVerifier(BaseVerifier):
    """Three-check verifier: file_exists + markdown_nonempty + topic_coverage.

    Designed for report-generation subtasks in multi-agent workflows.
    Topic keywords are passed via ``context["topic_keywords"]`` or
    ``target.metadata["topic_keywords"]``.
    """

    spec = VerifierSpec(
        name="ReportDeliverableVerifier",
        condition_type=VerifierConditionType.REPORT_DELIVERABLE,
        description=(
            "Verifies report deliverables: file exists, non-empty content, "
            "and topic keyword coverage"
        ),
        blocking=True,
        severity="normal",
        weight=1.0,
    )

    def __init__(self, config: Optional[ReportVerifierConfig] = None) -> None:
        self._cfg = config or ReportVerifierConfig()

    async def verify(
        self,
        target: "VerificationTarget",
        workspace: "SessionWorkspace",
        context: Optional[Dict[str, Any]] = None,
    ) -> "VerificationResult":
        if target.kind != "file":
            return self._make_result(
                target, VerificationStatus.SKIPPED,
                reason="ReportDeliverableVerifier skipped: target kind="
                       f"{target.kind}",
            )

        path = self._resolve_path(target, workspace)

        # ── Check 1: file_exists ────────────────────────────────────
        if path is None or not path.exists():
            return self._make_result(
                target, VerificationStatus.FAILED,
                reason=f"Report file not found: {target.path}",
                repair_hint="Re-run the writer subtask to produce the report",
            )

        # ── Check 2: markdown_nonempty ──────────────────────────────
        try:
            size = path.stat().st_size
        except OSError as exc:
            return self._make_result(
                target, VerificationStatus.FAILED,
                reason=f"Cannot stat file: {exc}",
            )

        if size < self._cfg.min_file_size_bytes:
            return self._make_result(
                target, VerificationStatus.FAILED,
                reason=(
                    f"Report too small: {size}B "
                    f"(min {self._cfg.min_file_size_bytes}B)"
                ),
                evidence={"path": str(path), "size_bytes": size},
                repair_hint="The report file appears empty or stub-only",
            )

        # ── Check 3: topic_coverage ─────────────────────────────────
        ext = path.suffix.lstrip(".").lower()
        if ext not in self._cfg.text_report_extensions:
            # Non-text report (e.g. docx, pdf) — skip topic check
            return self._make_result(
                target, VerificationStatus.PASSED,
                reason=(
                    f"Report exists ({size}B), extension .{ext} not "
                    "text-scannable — topic check skipped"
                ),
                evidence={"path": str(path), "size_bytes": size},
            )

        # Resolve topic keywords
        ctx = context or {}
        keywords: List[str] = []
        if "topic_keywords" in ctx:
            kw = ctx["topic_keywords"]
            keywords = kw if isinstance(kw, list) else [kw]
        elif target.metadata and "topic_keywords" in target.metadata:
            kw = target.metadata["topic_keywords"]
            keywords = kw if isinstance(kw, list) else [kw]

        if not keywords:
            # No keywords specified — pass on existence + size alone
            return self._make_result(
                target, VerificationStatus.PASSED,
                reason=f"Report exists and non-empty ({size}B), no topic keywords to check",
                evidence={"path": str(path), "size_bytes": size},
            )

        try:
            content = path.read_bytes()[:self._cfg.topic_scan_max_bytes]
            text_lower = content.decode("utf-8", errors="replace").lower()
        except Exception as exc:
            return self._make_result(
                target, VerificationStatus.UNCERTAIN,
                reason=f"Error reading report for topic scan: {exc}",
            )

        hits = [kw for kw in keywords if kw.lower() in text_lower]
        coverage = len(hits) / max(len(keywords), 1)

        if coverage >= self._cfg.topic_coverage_threshold:
            return self._make_result(
                target, VerificationStatus.PASSED,
                reason=(
                    f"Report verified: {size}B, topic coverage "
                    f"{coverage:.0%} ({len(hits)}/{len(keywords)})"
                ),
                evidence={
                    "path": str(path),
                    "size_bytes": size,
                    "topic_hits": hits,
                    "topic_total": len(keywords),
                    "coverage": round(coverage, 3),
                },
            )
        else:
            missing = [kw for kw in keywords if kw.lower() not in text_lower]
            return self._make_result(
                target, VerificationStatus.FAILED,
                reason=(
                    f"Topic coverage too low: {coverage:.0%} "
                    f"({len(hits)}/{len(keywords)}), "
                    f"threshold={self._cfg.topic_coverage_threshold:.0%}"
                ),
                evidence={
                    "path": str(path),
                    "size_bytes": size,
                    "topic_hits": hits,
                    "topic_missing": missing,
                    "coverage": round(coverage, 3),
                },
                repair_hint=f"Report is missing topics: {missing}",
            )
