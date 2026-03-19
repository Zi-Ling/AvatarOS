"""
ActionSchemaValidator — pre-execution schema gate for planner output.

Validates that every ADD_NODE in a GraphPatch carries the required
parameters for its target skill *before* the node enters the execution
graph.  This prevents invalid actions from polluting the runtime,
recovery pipeline, and evolution trace.

Design decisions:
- Uses skill_registry to obtain pydantic input_model JSON schema.
- Only checks `required` fields whose values are empty (None / "" / [] / {}).
- Returns a list of SchemaViolation; caller decides whether to hard-fail
  or inject a replan hint.
- Intentionally does NOT do full pydantic validation (that stays in
  skill_executor.py as the authoritative gate).  This is a lightweight
  pre-filter to catch obvious omissions early.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.graph_patch import GraphPatch

logger = logging.getLogger(__name__)


@dataclass
class SchemaViolation:
    """One missing-required-param violation."""
    node_id: str
    skill_name: str
    missing_params: List[str]

    def to_hint(self) -> str:
        return (
            f"Skill '{self.skill_name}' (node {self.node_id}) is missing "
            f"required parameter(s): {', '.join(self.missing_params)}. "
            f"You MUST provide all required parameters."
        )


@dataclass
class BinaryFormatViolation:
    """Violation: text-only skill targeting a binary file format."""
    node_id: str
    skill_name: str
    path: str
    extension: str

    def to_hint(self) -> str:
        return (
            f"Skill '{self.skill_name}' (node {self.node_id}) targets "
            f"binary format '.{self.extension}' (path: {self.path}). "
            f"fs.write/fs.read are TEXT-ONLY and CANNOT produce valid "
            f"binary files. Use python.run with the appropriate library "
            f"(e.g. python-docx for .docx, openpyxl for .xlsx, "
            f"python-pptx for .pptx) instead."
        )


# Binary extensions that cannot be correctly handled by text I/O skills
_BINARY_EXTENSIONS = frozenset({
    "docx", "xlsx", "pptx", "pdf", "zip", "tar", "gz", "bz2", "7z",
    "rar", "png", "jpg", "jpeg", "gif", "bmp", "tiff", "webp", "ico",
    "mp3", "mp4", "wav", "avi", "mkv", "mov", "flac", "ogg",
    "exe", "dll", "so", "dylib", "whl", "egg",
    "sqlite", "db", "parquet", "feather", "arrow",
})


def validate_patch_schemas(patch: 'GraphPatch') -> List[SchemaViolation]:
    """
    Check every ADD_NODE action in *patch* for missing required params
    and binary format misuse.

    Returns a list of SchemaViolation (empty == all good).
    """
    from app.avatar.runtime.graph.models.graph_patch import PatchOperation

    violations: List[SchemaViolation] = []

    for action in patch.actions:
        if action.operation != PatchOperation.ADD_NODE or action.node is None:
            continue

        skill_name = action.node.capability_name
        params = action.node.params or {}

        # Check 1: missing required params
        missing = _get_missing_required(skill_name, params)
        if missing:
            violations.append(SchemaViolation(
                node_id=action.node.id,
                skill_name=skill_name,
                missing_params=missing,
            ))
            logger.warning(
                f"[ActionSchemaValidator] {skill_name} (node={action.node.id}) "
                f"missing required params: {missing}"
            )

        # Check 2: text-only skill targeting binary format
        binary_v = _check_binary_format_misuse(action.node.id, skill_name, params)
        if binary_v:
            violations.append(binary_v)
            logger.warning(
                f"[ActionSchemaValidator] {skill_name} (node={action.node.id}) "
                f"targets binary format '.{binary_v.extension}'"
            )

    return violations


def _get_missing_required(skill_name: str, params: Dict[str, Any]) -> List[str]:
    """Return list of required param names that are empty in *params*."""
    try:
        from app.avatar.skills.registry import skill_registry
        skill_cls = skill_registry.get(skill_name)
        if not skill_cls or not skill_cls.spec.input_model:
            return []
        schema = skill_cls.spec.input_model.model_json_schema()
    except Exception:
        return []

    required = schema.get("required", [])
    if not required:
        return []

    missing = []
    for param_name in required:
        val = params.get(param_name)
        if val is None or val == "" or val == [] or val == {}:
            missing.append(param_name)

    return missing


def _check_binary_format_misuse(
    node_id: str,
    skill_name: str,
    params: Dict[str, Any],
) -> Optional['BinaryFormatViolation']:
    """Block text-only skills (fs.write, fs.read) targeting binary file formats."""
    _TEXT_ONLY_SKILLS = {"fs.write", "fs.read"}
    if skill_name not in _TEXT_ONLY_SKILLS:
        return None

    # Extract path from params — try common param names
    path = params.get("path") or params.get("file_path") or params.get("filepath") or ""
    if not path or not isinstance(path, str):
        return None

    # Check extension
    if "." not in path:
        return None
    ext = path.rsplit(".", 1)[-1].lower()
    if ext in _BINARY_EXTENSIONS:
        return BinaryFormatViolation(
            node_id=node_id,
            skill_name=skill_name,
            path=path,
            extension=ext,
        )
    return None
