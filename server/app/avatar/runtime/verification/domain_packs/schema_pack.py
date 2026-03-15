"""
Schema-level verifier pack (Phase 3).

Provides:
  JsonSchemaVerifier  — validates JSON against a JSON Schema
  CsvColumnVerifier   — validates CSV has required columns

Both are schema-level (deeper than shell-level FileExists/JsonParseable).
"""
from __future__ import annotations

import csv
import io
import json
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type

from app.avatar.runtime.verification.models import (
    VerificationResult,
    VerificationStatus,
    VerifierConditionType,
    VerifierSpec,
)
from app.avatar.runtime.verification.verifier_registry import DomainVerifierPack
from app.avatar.runtime.verification.verifiers.base import BaseVerifier

if TYPE_CHECKING:
    from app.avatar.runtime.verification.models import VerificationTarget
    from app.avatar.runtime.workspace.session_workspace import SessionWorkspace

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JsonSchemaVerifier
# ---------------------------------------------------------------------------

class JsonSchemaVerifier(BaseVerifier):
    """
    Validates a JSON file against a JSON Schema.

    Schema is passed via context["json_schema"] or target.metadata["json_schema"].
    Requires jsonschema package (optional dep). Returns SKIPPED if unavailable.
    """

    spec = VerifierSpec(
        name="JsonSchemaVerifier",
        condition_type=VerifierConditionType.JSON_SCHEMA,
        description="Validates JSON file against a JSON Schema",
        blocking=True,
        severity="normal",
        weight=1.0,
    )

    async def verify(
        self,
        target: "VerificationTarget",
        workspace: "SessionWorkspace",
        context: Optional[Dict[str, Any]] = None,
    ) -> VerificationResult:
        if target.kind != "file":
            return self._make_result(
                target, VerificationStatus.SKIPPED,
                reason="JsonSchemaVerifier skipped: not a file target",
            )

        # Resolve schema
        schema: Optional[dict] = None
        if context and "json_schema" in context:
            schema = context["json_schema"]
        elif target.metadata and "json_schema" in target.metadata:
            schema = target.metadata["json_schema"]

        if schema is None:
            return self._make_result(
                target, VerificationStatus.SKIPPED,
                reason="JsonSchemaVerifier skipped: no schema provided",
            )

        # Optional dep check
        try:
            import jsonschema  # type: ignore
        except ImportError:
            return self._make_result(
                target, VerificationStatus.SKIPPED,
                reason="jsonschema package not installed",
            )

        path = self._resolve_path(target, workspace)
        if path is None or not path.exists():
            return self._make_result(
                target, VerificationStatus.FAILED,
                reason=f"File not found: {target.path}",
            )

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            data = json.loads(content)
            jsonschema.validate(instance=data, schema=schema)
            return self._make_result(
                target, VerificationStatus.PASSED,
                reason="JSON validates against schema",
                evidence={"path": str(path)},
            )
        except json.JSONDecodeError as e:
            return self._make_result(
                target, VerificationStatus.FAILED,
                reason=f"JSON parse error: {e}",
                repair_hint="Fix JSON syntax before schema validation",
            )
        except Exception as e:
            return self._make_result(
                target, VerificationStatus.FAILED,
                reason=f"Schema validation failed: {e}",
                evidence={"error": str(e)[:200]},
                repair_hint="Ensure output matches the required schema",
            )


# ---------------------------------------------------------------------------
# CsvColumnVerifier
# ---------------------------------------------------------------------------

class CsvColumnVerifier(BaseVerifier):
    """
    Validates that a CSV file contains required columns.

    Required columns passed via context["required_columns"] or
    target.metadata["required_columns"] (list of str).
    """

    spec = VerifierSpec(
        name="CsvColumnVerifier",
        condition_type=VerifierConditionType.CSV_COLUMNS,
        description="Validates CSV file has required columns",
        blocking=True,
        severity="normal",
        weight=1.0,
    )

    async def verify(
        self,
        target: "VerificationTarget",
        workspace: "SessionWorkspace",
        context: Optional[Dict[str, Any]] = None,
    ) -> VerificationResult:
        if target.kind != "file":
            return self._make_result(
                target, VerificationStatus.SKIPPED,
                reason="CsvColumnVerifier skipped: not a file target",
            )

        # Resolve required columns
        required_cols: List[str] = []
        if context and "required_columns" in context:
            required_cols = context["required_columns"]
        elif target.metadata and "required_columns" in target.metadata:
            required_cols = target.metadata["required_columns"]

        if not required_cols:
            return self._make_result(
                target, VerificationStatus.SKIPPED,
                reason="CsvColumnVerifier skipped: no required_columns specified",
            )

        path = self._resolve_path(target, workspace)
        if path is None or not path.exists():
            return self._make_result(
                target, VerificationStatus.FAILED,
                reason=f"CSV file not found: {target.path}",
            )

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            reader = csv.reader(io.StringIO(content))
            header = next(reader, None)
            if header is None:
                return self._make_result(
                    target, VerificationStatus.FAILED,
                    reason="CSV file is empty (no header row)",
                )

            actual_cols = [c.strip() for c in header]
            missing = [c for c in required_cols if c not in actual_cols]
            if not missing:
                return self._make_result(
                    target, VerificationStatus.PASSED,
                    reason=f"All {len(required_cols)} required column(s) present",
                    evidence={"columns": actual_cols, "required": required_cols},
                )
            else:
                return self._make_result(
                    target, VerificationStatus.FAILED,
                    reason=f"Missing column(s): {missing}",
                    evidence={"missing": missing, "actual": actual_cols},
                    repair_hint=f"Ensure CSV output includes columns: {missing}",
                )
        except Exception as e:
            return self._make_result(
                target, VerificationStatus.UNCERTAIN,
                reason=f"Error reading CSV: {e}",
            )


# ---------------------------------------------------------------------------
# SchemaVerifierPack
# ---------------------------------------------------------------------------

class SchemaVerifierPack(DomainVerifierPack):
    """Domain pack providing schema-level verifiers."""

    def get_verifiers(self) -> List[Type[BaseVerifier]]:
        return [JsonSchemaVerifier, CsvColumnVerifier]
