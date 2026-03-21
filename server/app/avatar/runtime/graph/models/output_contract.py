"""
TypedOutputContract — unified Skill output contract.

Separates ValueKind (content type) from TransportMode (delivery mechanism),
replacing the old flat enum that mixed both concerns.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Core enums
# ---------------------------------------------------------------------------

class ValueKind(str, Enum):
    """Content type of the skill output — describes *what* the data is."""
    TEXT = "text"
    JSON = "json"
    TABLE = "table"
    BINARY = "binary"
    PATH = "path"


class TransportMode(str, Enum):
    """Delivery mechanism — describes *how* the data is transported."""
    INLINE = "inline"      # content embedded directly in the output dict
    REF = "ref"            # reference (artifact_id or file path)
    ARTIFACT = "artifact"  # registered as a first-class ArtifactRegistry citizen


class ArtifactRole(str, Enum):
    """Role of the artifact in the skill output."""
    PRODUCED = "produced"      # newly generated product → register in ArtifactRegistry
    REFERENCED = "referenced"  # existing resource reference → do NOT create new record
    CONSUMED = "consumed"      # input consumed → do NOT create new record


class OutputCompatMode(str, Enum):
    """Migration compatibility mode for legacy skill outputs."""
    STRICT = "strict"        # reject output missing value_kind, record invalid_output_contract
    COMPATIBLE = "compatible"  # infer value_kind with deprecation warning (default)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class InvalidOutputContractError(ValueError):
    """Raised in STRICT mode when value_kind is missing from skill output."""
    pass


class InvalidTransportError(ValueError):
    """Raised when value_kind=BINARY + transport_mode=INLINE is detected."""
    pass


# ---------------------------------------------------------------------------
# Contract dataclass
# ---------------------------------------------------------------------------

@dataclass
class SkillOutputContract:
    """
    Complete output contract for a skill execution.

    Constraints:
    - value_kind=BINARY + transport_mode=INLINE is always invalid.
    - artifact_id must be set when transport_mode=ARTIFACT.
    """
    value_kind: ValueKind
    transport_mode: TransportMode
    artifact_role: ArtifactRole = ArtifactRole.PRODUCED
    artifact_id: Optional[str] = None       # filled when transport_mode=ARTIFACT
    schema: Optional[Dict[str, Any]] = None  # JSON Schema when value_kind=JSON
    mime_type: Optional[str] = None          # MIME type when value_kind=BINARY
    semantic_label: Optional[str] = None     # e.g. "output_report"

    def __post_init__(self) -> None:
        validate_output_contract(self)


def validate_output_contract(contract: SkillOutputContract) -> None:
    """
    Validate a SkillOutputContract.
    Raises InvalidTransportError for BINARY+INLINE combination.
    """
    if (
        contract.value_kind == ValueKind.BINARY
        and contract.transport_mode == TransportMode.INLINE
    ):
        raise InvalidTransportError(
            "value_kind=BINARY with transport_mode=INLINE is not allowed. "
            "Binary content must use transport_mode=ARTIFACT."
        )


# ---------------------------------------------------------------------------
# Migration adapter
# ---------------------------------------------------------------------------

class OutputContractAdapter:
    """
    Migrate legacy skill outputs (hex/stdout/result/output fields) to TypedOutputContract.

    Compatible mode (default): infer value_kind, emit DeprecationWarning.
    Strict mode: reject outputs missing value_kind, raise InvalidOutputContractError.
    """

    def adapt(
        self,
        raw_output: Dict[str, Any],
        mode: OutputCompatMode = OutputCompatMode.COMPATIBLE,
        trace_store: Any = None,
        session_id: Optional[str] = None,
        skill_name: Optional[str] = None,
    ) -> SkillOutputContract:
        """
        Convert raw skill output dict to SkillOutputContract.

        Resolution order:
        1. raw_output contains value_kind + transport_mode → use directly
        2. skill_name provided → lookup SkillSpec.output_contract from registry
        3. Compatible mode → infer from output fields + DeprecationWarning
        4. Strict mode → raise InvalidOutputContractError
        """
        # 1. If already typed in output dict, return directly
        if "value_kind" in raw_output and "transport_mode" in raw_output:
            try:
                vk = ValueKind(raw_output["value_kind"])
                tm = TransportMode(raw_output["transport_mode"])
                role = ArtifactRole(raw_output.get("artifact_role", ArtifactRole.PRODUCED))
                return SkillOutputContract(
                    value_kind=vk,
                    transport_mode=tm,
                    artifact_role=role,
                    artifact_id=raw_output.get("artifact_id"),
                    schema=raw_output.get("schema"),
                    mime_type=raw_output.get("mime_type"),
                    semantic_label=raw_output.get("semantic_label"),
                )
            except (ValueError, InvalidTransportError):
                pass

        # 2. Lookup from SkillSpec.output_contract (declarative, no warning)
        if skill_name:
            try:
                from app.avatar.skills.registry import skill_registry
                skill_cls = skill_registry.get(skill_name)
                if skill_cls and skill_cls.spec.output_contract is not None:
                    return skill_cls.spec.output_contract
            except Exception:
                pass

        if mode == OutputCompatMode.STRICT:
            if trace_store and session_id:
                try:
                    trace_store.record_event(
                        session_id=session_id,
                        event_type="invalid_output_contract",
                        payload={"raw_output_keys": list(raw_output.keys())},
                    )
                except Exception:
                    pass
            raise InvalidOutputContractError(
                f"Output missing value_kind field in STRICT mode. "
                f"Keys present: {list(raw_output.keys())}"
            )

        # Compatible mode: infer
        value_kind = self._infer_value_kind(raw_output)
        transport_mode = self._infer_transport_mode(raw_output, value_kind)

        warnings.warn(
            f"Skill output missing value_kind/transport_mode fields. "
            f"Inferred: value_kind={value_kind.value}, transport_mode={transport_mode.value}. "
            f"Please update skill to return SkillOutputContract explicitly.",
            DeprecationWarning,
            stacklevel=3,
        )

        return SkillOutputContract(
            value_kind=value_kind,
            transport_mode=transport_mode,
            artifact_role=ArtifactRole.PRODUCED,
            artifact_id=raw_output.get("artifact_id"),
            mime_type=raw_output.get("mime_type"),
            semantic_label=raw_output.get("semantic_label"),
        )

    def _infer_value_kind(self, raw_output: Dict[str, Any]) -> ValueKind:
        """Infer ValueKind from legacy output fields."""
        if "hex" in raw_output:
            return ValueKind.BINARY
        if "file_path" in raw_output or "output_path" in raw_output:
            return ValueKind.PATH
        # Check output/result field type
        for key in ("output", "result"):
            val = raw_output.get(key)
            if val is not None:
                if isinstance(val, dict):
                    return ValueKind.JSON
                if isinstance(val, str):
                    return ValueKind.TEXT
        if "stdout" in raw_output:
            return ValueKind.TEXT
        return ValueKind.TEXT

    def _infer_transport_mode(
        self, raw_output: Dict[str, Any], vk: ValueKind
    ) -> TransportMode:
        """Infer TransportMode from legacy output fields and inferred ValueKind."""
        if vk == ValueKind.BINARY:
            return TransportMode.ARTIFACT
        if vk == ValueKind.PATH:
            return TransportMode.REF
        return TransportMode.INLINE
