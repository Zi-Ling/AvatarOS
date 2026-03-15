"""
GoalNormalizer — converts free-form goal strings into structured NormalizedGoal.

Parsing strategy (priority order):
  1. Keyword matching (file extensions, verbs, domain words)
  2. Artifact path extraction (regex)
  3. Heuristic fallback (risk_level=HIGH, requires_human_approval=True)
"""
from __future__ import annotations

import re
from typing import List, Optional

from app.avatar.runtime.verification.models import (
    ExpectedArtifact,
    NormalizedGoal,
    RiskLevel,
)

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword tables
# ---------------------------------------------------------------------------

_HIGH_RISK_KEYWORDS = frozenset({
    "send", "email", "mail", "smtp", "http", "https", "request", "post", "upload",
    "deploy", "delete", "remove", "drop", "truncate", "format", "install",
    "execute", "run", "shell", "bash", "cmd", "command", "script",
    "bulk", "batch", "all files", "recursive",
    "network", "api", "webhook", "socket",
})

_MEDIUM_RISK_KEYWORDS = frozenset({
    "write", "save", "create", "generate", "export", "convert", "transform",
    "process", "parse", "extract", "merge", "split", "resize", "compress",
    "encode", "decode", "update", "modify", "edit", "patch",
})

_LOW_RISK_KEYWORDS = frozenset({
    "read", "list", "show", "display", "print", "summarize", "describe",
    "analyze", "check", "verify", "count", "search", "find", "query",
    "report", "review", "inspect",
})

# extension → (mime_type, condition_type)
_EXT_MAP = {
    ".json": ("application/json", "json_parseable"),
    ".csv":  ("text/csv",         "csv_has_data"),
    ".png":  ("image/png",        "image_openable"),
    ".jpg":  ("image/jpeg",       "image_openable"),
    ".jpeg": ("image/jpeg",       "image_openable"),
    ".gif":  ("image/gif",        "image_openable"),
    ".bmp":  ("image/bmp",        "image_openable"),
    ".webp": ("image/webp",       "image_openable"),
    ".txt":  ("text/plain",       "file_exists"),
    ".md":   ("text/markdown",    "file_exists"),
    ".pdf":  ("application/pdf",  "file_exists"),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "file_exists"),
    ".xls":  ("application/vnd.ms-excel", "file_exists"),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "file_exists"),
    ".zip":  ("application/zip",  "file_exists"),
    ".html": ("text/html",        "file_exists"),
    ".xml":  ("application/xml",  "file_exists"),
    ".yaml": ("application/yaml", "file_exists"),
    ".yml":  ("application/yaml", "file_exists"),
    ".py":   ("text/x-python",    "file_exists"),
}

# goal_type inference
_GOAL_TYPE_MAP = {
    "file_transform": frozenset({"convert", "transform", "resize", "compress", "encode", "decode"}),
    "report_gen":     frozenset({"report", "summarize", "summary", "generate report", "create report"}),
    "data_analysis":  frozenset({"analyze", "analysis", "statistics", "count", "aggregate"}),
    "file_write":     frozenset({"write", "save", "create file", "export", "generate file"}),
    "data_fetch":     frozenset({"fetch", "download", "get", "retrieve", "scrape"}),
    "query":          frozenset({"query", "search", "find", "list", "show"}),
}

# path-like pattern
_PATH_RE = re.compile(
    r'(?:^|[\s\'"])([./~][\w./\-*?]+\.\w{2,6})',
    re.MULTILINE,
)


class GoalNormalizer:
    """Converts a free-form goal string into a structured NormalizedGoal."""

    def normalize(self, goal: str) -> NormalizedGoal:
        if not goal or not goal.strip():
            return self._fallback(goal or "")

        goal_lower = goal.lower()

        artifacts = self._extract_artifacts(goal)
        risk_level = self._infer_risk_level(goal_lower, artifacts)
        goal_type = self._infer_goal_type(goal_lower)
        verification_intents = self._infer_intents(artifacts, goal_lower)
        sub_goals = self._decompose_sub_goals(goal)

        # P3: DomainPack matching
        matched_domain_pack = self._match_domain_pack(goal_lower)

        return NormalizedGoal(
            original=goal,
            goal_type=goal_type,
            expected_artifacts=artifacts,
            verification_intents=verification_intents,
            risk_level=risk_level,
            requires_human_approval=(risk_level == RiskLevel.HIGH),
            sub_goals=sub_goals,
            matched_domain_pack=matched_domain_pack,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_artifacts(self, goal: str) -> List[ExpectedArtifact]:
        artifacts: List[ExpectedArtifact] = []
        seen_paths: set = set()

        # 1. Explicit path patterns
        for m in _PATH_RE.finditer(goal):
            path = m.group(1)
            if path in seen_paths:
                continue
            seen_paths.add(path)
            ext = self._get_ext(path)
            mime, _ = _EXT_MAP.get(ext, (None, None))
            artifacts.append(ExpectedArtifact(
                label=f"file:{path}",
                mime_type=mime,
                path_hint=path,
                required=True,
            ))

        # 2. Extension mentions without full path
        if not artifacts:
            for ext, (mime, _) in _EXT_MAP.items():
                if ext.lstrip(".") in goal.lower():
                    artifacts.append(ExpectedArtifact(
                        label=f"output_{ext.lstrip('.')}",
                        mime_type=mime,
                        path_hint=f"output/*{ext}",
                        required=True,
                    ))
                    break  # one hint is enough for fallback

        return artifacts

    def _infer_risk_level(self, goal_lower: str, artifacts: List[ExpectedArtifact]) -> RiskLevel:
        words = set(re.split(r'\W+', goal_lower))
        if words & _HIGH_RISK_KEYWORDS:
            return RiskLevel.HIGH
        if words & _MEDIUM_RISK_KEYWORDS or artifacts:
            return RiskLevel.MEDIUM
        if words & _LOW_RISK_KEYWORDS:
            return RiskLevel.LOW
        return RiskLevel.MEDIUM  # safe default

    def _infer_goal_type(self, goal_lower: str) -> str:
        for gtype, keywords in _GOAL_TYPE_MAP.items():
            for kw in keywords:
                if kw in goal_lower:
                    return gtype
        return "general"

    def _infer_intents(self, artifacts: List[ExpectedArtifact], goal_lower: str) -> List[str]:
        intents: List[str] = []
        seen: set = set()

        for art in artifacts:
            ext = self._get_ext(art.path_hint or "")
            _, ctype = _EXT_MAP.get(ext, (None, None))
            if ctype and ctype not in seen:
                intents.append(ctype)
                seen.add(ctype)
            elif "file_exists" not in seen:
                intents.append("file_exists")
                seen.add("file_exists")

        # keyword-based intent hints
        if "json" in goal_lower and "json_parseable" not in seen:
            intents.append("json_parseable")
        if any(w in goal_lower for w in ("image", "photo", "picture", "图片", "图像")) and "image_openable" not in seen:
            intents.append("image_openable")
        if "csv" in goal_lower and "csv_has_data" not in seen:
            intents.append("csv_has_data")

        if not intents:
            intents.append("file_exists")

        return intents

    def _decompose_sub_goals(self, goal: str) -> List[str]:
        """Simple heuristic: split on conjunctions / numbered lists."""
        # numbered list: "1. ... 2. ..."
        numbered = re.split(r'\d+\.\s+', goal)
        if len(numbered) > 2:
            return [s.strip() for s in numbered if s.strip()]

        # conjunction split
        parts = re.split(r'\s+(?:and|then|after that|finally|also|additionally)\s+', goal, flags=re.IGNORECASE)
        if len(parts) > 1:
            return [p.strip() for p in parts if p.strip()]

        return [goal.strip()]

    @staticmethod
    def _get_ext(path: str) -> str:
        if not path:
            return ""
        dot = path.rfind(".")
        if dot == -1:
            return ""
        return path[dot:].lower().split("?")[0]  # strip query strings

    def _fallback(self, goal: str) -> NormalizedGoal:
        logger.warning(f"[GoalNormalizer] Cannot parse goal, using HIGH-risk fallback: {goal!r}")
        return NormalizedGoal(
            original=goal,
            goal_type="unknown",
            expected_artifacts=[],
            verification_intents=["file_exists"],
            risk_level=RiskLevel.HIGH,
            requires_human_approval=True,
            sub_goals=[],
        )

    def _match_domain_pack(self, goal_lower: str) -> Optional[str]:
        """
        P3: Match goal against BUILTIN_DOMAIN_PACKS.supported_goal_types.
        Returns pack_id of first matching pack, or None.
        """
        try:
            from fnmatch import fnmatch
            from app.avatar.runtime.verification.domain_packs.builtin import BUILTIN_DOMAIN_PACKS
            for pack_id, pack in BUILTIN_DOMAIN_PACKS.items():
                for pattern in pack.supported_goal_types:
                    if fnmatch(goal_lower, pattern.lower()):
                        logger.debug(f"[GoalNormalizer] Matched DomainPack: {pack_id} (pattern={pattern})")
                        return pack_id
        except Exception as e:
            logger.debug(f"[GoalNormalizer] DomainPack matching failed: {e}")
        return None
