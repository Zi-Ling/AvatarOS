"""
Built-in shell-level verifiers (Phase 1).

All five verifiers operate at the shell level:
  FileExistsVerifier    — file exists on disk
  JsonParseableVerifier — file is valid JSON
  ImageOpenableVerifier — file is openable as an image (PIL optional dep)
  CsvHasDataVerifier    — CSV has at least one data row (excluding header)
  TextContainsVerifier  — file text contains expected keyword(s)
"""
from __future__ import annotations

import csv
import io
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

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


# ---------------------------------------------------------------------------
# FileExistsVerifier
# ---------------------------------------------------------------------------

class FileExistsVerifier(BaseVerifier):
    """Verifies that the target file exists on disk."""

    spec = VerifierSpec(
        name="FileExistsVerifier",
        condition_type=VerifierConditionType.FILE_EXISTS,
        description="Checks that the target file exists on disk",
        blocking=True,
        severity="normal",
        weight=1.0,
    )

    async def verify(
        self,
        target: "VerificationTarget",
        workspace: "SessionWorkspace",
        context: Optional[Dict[str, Any]] = None,
    ) -> "VerificationResult":
        if target.kind not in ("file", "directory"):
            return self._make_result(
                target, VerificationStatus.SKIPPED,
                reason=f"FileExistsVerifier skipped: target kind={target.kind}",
            )

        path = self._resolve_path(target, workspace)
        if path is None:
            return self._make_result(
                target, VerificationStatus.FAILED,
                reason="No path specified in target",
                repair_hint="Ensure the task produces a file at the expected path",
            )

        if path.exists():
            size = path.stat().st_size if path.is_file() else None
            return self._make_result(
                target, VerificationStatus.PASSED,
                reason=f"File exists: {path}",
                evidence={"path": str(path), "size_bytes": size},
            )
        else:
            return self._make_result(
                target, VerificationStatus.FAILED,
                reason=f"File not found: {path}",
                repair_hint=f"Re-run the step that should produce {path.name}",
            )


# ---------------------------------------------------------------------------
# JsonParseableVerifier
# ---------------------------------------------------------------------------

class JsonParseableVerifier(BaseVerifier):
    """Verifies that the target file is valid JSON."""

    spec = VerifierSpec(
        name="JsonParseableVerifier",
        condition_type=VerifierConditionType.JSON_PARSEABLE,
        description="Checks that the target file can be parsed as JSON",
        blocking=True,
        severity="normal",
        weight=1.0,
    )

    async def verify(
        self,
        target: "VerificationTarget",
        workspace: "SessionWorkspace",
        context: Optional[Dict[str, Any]] = None,
    ) -> "VerificationResult":
        if target.kind != "file":
            return self._make_result(
                target, VerificationStatus.SKIPPED,
                reason=f"JsonParseableVerifier skipped: target kind={target.kind}",
            )

        path = self._resolve_path(target, workspace)
        if path is None or not path.exists():
            return self._make_result(
                target, VerificationStatus.FAILED,
                reason=f"File not found: {target.path}",
                repair_hint="Ensure the JSON file is produced before verification",
            )

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            parsed = json.loads(content)
            top_type = type(parsed).__name__
            return self._make_result(
                target, VerificationStatus.PASSED,
                reason=f"Valid JSON ({top_type})",
                evidence={"path": str(path), "top_level_type": top_type},
            )
        except json.JSONDecodeError as e:
            return self._make_result(
                target, VerificationStatus.FAILED,
                reason=f"JSON parse error: {e}",
                evidence={"error": str(e), "path": str(path)},
                repair_hint="Fix the JSON syntax error in the output file",
            )
        except Exception as e:
            return self._make_result(
                target, VerificationStatus.UNCERTAIN,
                reason=f"Unexpected error reading file: {e}",
            )


# ---------------------------------------------------------------------------
# ImageOpenableVerifier
# ---------------------------------------------------------------------------

class ImageOpenableVerifier(BaseVerifier):
    """
    Verifies that the target file can be opened as an image.
    Requires Pillow (PIL). If PIL is not installed, returns SKIPPED.
    """

    spec = VerifierSpec(
        name="ImageOpenableVerifier",
        condition_type=VerifierConditionType.IMAGE_OPENABLE,
        description="Checks that the target file can be opened as an image via PIL",
        blocking=True,
        severity="normal",
        weight=1.0,
    )

    async def verify(
        self,
        target: "VerificationTarget",
        workspace: "SessionWorkspace",
        context: Optional[Dict[str, Any]] = None,
    ) -> "VerificationResult":
        if target.kind != "file":
            return self._make_result(
                target, VerificationStatus.SKIPPED,
                reason=f"ImageOpenableVerifier skipped: target kind={target.kind}",
            )

        # Optional dependency check
        try:
            from PIL import Image  # type: ignore
        except ImportError:
            return self._make_result(
                target, VerificationStatus.SKIPPED,
                reason="Pillow (PIL) not installed — ImageOpenableVerifier skipped",
            )

        path = self._resolve_path(target, workspace)
        if path is None or not path.exists():
            return self._make_result(
                target, VerificationStatus.FAILED,
                reason=f"Image file not found: {target.path}",
                repair_hint="Ensure the image file is produced before verification",
            )

        try:
            with Image.open(path) as img:
                fmt = img.format
                size = img.size
                mode = img.mode
            return self._make_result(
                target, VerificationStatus.PASSED,
                reason=f"Image openable: format={fmt}, size={size}, mode={mode}",
                evidence={"path": str(path), "format": fmt, "size": size, "mode": mode},
            )
        except Exception as e:
            return self._make_result(
                target, VerificationStatus.FAILED,
                reason=f"Cannot open image: {e}",
                evidence={"error": str(e), "path": str(path)},
                repair_hint="The image file may be corrupt or incomplete",
            )


# ---------------------------------------------------------------------------
# CsvHasDataVerifier
# ---------------------------------------------------------------------------

class CsvHasDataVerifier(BaseVerifier):
    """Verifies that the target CSV file has at least one data row (excluding header)."""

    spec = VerifierSpec(
        name="CsvHasDataVerifier",
        condition_type=VerifierConditionType.CSV_HAS_DATA,
        description="Checks that the CSV file has at least one data row (excluding header)",
        blocking=True,
        severity="normal",
        weight=1.0,
    )

    async def verify(
        self,
        target: "VerificationTarget",
        workspace: "SessionWorkspace",
        context: Optional[Dict[str, Any]] = None,
    ) -> "VerificationResult":
        if target.kind != "file":
            return self._make_result(
                target, VerificationStatus.SKIPPED,
                reason=f"CsvHasDataVerifier skipped: target kind={target.kind}",
            )

        path = self._resolve_path(target, workspace)
        if path is None or not path.exists():
            return self._make_result(
                target, VerificationStatus.FAILED,
                reason=f"CSV file not found: {target.path}",
                repair_hint="Ensure the CSV file is produced before verification",
            )

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            reader = csv.reader(io.StringIO(content))
            rows = list(reader)
            # rows[0] is header (if any), data rows start at index 1
            data_rows = len(rows) - 1 if rows else 0
            if data_rows > 0:
                cols = len(rows[0]) if rows else 0
                return self._make_result(
                    target, VerificationStatus.PASSED,
                    reason=f"CSV has {data_rows} data row(s), {cols} column(s)",
                    evidence={"path": str(path), "data_rows": data_rows, "columns": cols},
                )
            else:
                return self._make_result(
                    target, VerificationStatus.FAILED,
                    reason="CSV file has no data rows (empty or header-only)",
                    evidence={"path": str(path), "total_rows": len(rows)},
                    repair_hint="The CSV output is empty — re-run the data extraction step",
                )
        except Exception as e:
            return self._make_result(
                target, VerificationStatus.UNCERTAIN,
                reason=f"Error reading CSV: {e}",
                evidence={"error": str(e)},
            )


# ---------------------------------------------------------------------------
# TextContainsVerifier
# ---------------------------------------------------------------------------

class TextContainsVerifier(BaseVerifier):
    """
    Advisory verifier: checks that the file text contains expected keyword(s).
    Non-blocking (severity=advisory).
    Keywords are passed via context["expected_keywords"] or target.metadata["keywords"].
    """

    spec = VerifierSpec(
        name="TextContainsVerifier",
        condition_type=VerifierConditionType.TEXT_CONTAINS,
        description="Checks that the file text contains expected keyword(s) (advisory)",
        blocking=False,
        severity="advisory",
        weight=0.5,
    )

    async def verify(
        self,
        target: "VerificationTarget",
        workspace: "SessionWorkspace",
        context: Optional[Dict[str, Any]] = None,
    ) -> "VerificationResult":
        if target.kind != "file":
            return self._make_result(
                target, VerificationStatus.SKIPPED,
                reason=f"TextContainsVerifier skipped: target kind={target.kind}",
            )

        # Resolve keywords from context or target metadata
        keywords: List[str] = []
        if context and "expected_keywords" in context:
            kw = context["expected_keywords"]
            keywords = kw if isinstance(kw, list) else [kw]
        elif target.metadata and "keywords" in target.metadata:
            kw = target.metadata["keywords"]
            keywords = kw if isinstance(kw, list) else [kw]

        if not keywords:
            return self._make_result(
                target, VerificationStatus.SKIPPED,
                reason="TextContainsVerifier skipped: no keywords specified",
            )

        path = self._resolve_path(target, workspace)
        if path is None or not path.exists():
            return self._make_result(
                target, VerificationStatus.FAILED,
                reason=f"File not found: {target.path}",
            )

        try:
            content = path.read_text(encoding="utf-8", errors="replace").lower()
            missing = [kw for kw in keywords if kw.lower() not in content]
            if not missing:
                return self._make_result(
                    target, VerificationStatus.PASSED,
                    reason=f"All {len(keywords)} keyword(s) found in file",
                    evidence={"keywords": keywords, "path": str(path)},
                )
            else:
                return self._make_result(
                    target, VerificationStatus.FAILED,
                    reason=f"Missing keyword(s): {missing}",
                    evidence={"missing": missing, "expected": keywords},
                    repair_hint=f"Ensure the output contains: {missing}",
                )
        except Exception as e:
            return self._make_result(
                target, VerificationStatus.UNCERTAIN,
                reason=f"Error reading file: {e}",
            )
