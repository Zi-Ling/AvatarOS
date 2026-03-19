"""
Inter-step type validation data models.

Provides compatibility level classification, unknown reason codes,
and structured validation results for the InterStepTypeValidator.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .schema import TransformationKind


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CompatibilityLevel(str, Enum):
    """Type compatibility verification result level."""
    COMPATIBLE = "compatible"                  # natively compatible
    ADAPTER_COMPATIBLE = "adapter_compatible"  # compatible via adapter
    INCOMPATIBLE = "incompatible"              # incompatible
    UNKNOWN = "unknown"                        # cannot determine


class UnknownReasonCode(str, Enum):
    """
    Concrete reason code for UNKNOWN compatibility results.

    V1 values — validators MUST use these enum members; free-form strings
    are forbidden.
    """
    SOURCE_SCHEMA_MISSING = "source_schema_missing"
    TARGET_SCHEMA_MISSING = "target_schema_missing"
    BINDING_MISSING = "binding_missing"
    PROJECTED_FIELD_NOT_FOUND = "projected_field_not_found"
    TRANSFORMATION_UNRESOLVABLE = "transformation_unresolvable"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    """Structured result of an inter-step type validation check."""
    level: CompatibilityLevel
    source_node_id: str = ""
    source_field: str = ""
    source_type: str = ""
    target_param: str = ""
    target_expected_type: str = ""
    transformation_kind: Optional[TransformationKind] = None
    adapter_name: Optional[str] = None
    unknown_reason: Optional[UnknownReasonCode] = None  # only set when level == UNKNOWN
    message: str = ""
    schema_version: str = "1.0.0"


import logging
from typing import Optional as _Optional

from .schema import (
    FieldSchema,
    ParamBindingSpec,
    ParameterSpec,
    SkillInputSchema,
    StepOutputSchema,
)

_logger = logging.getLogger(__name__)


class InterStepTypeValidator:
    """Validates type compatibility between connected steps.

    Validation flow:
    1. Check for missing schemas/binding → UNKNOWN with reason code
    2. Resolve source field and target param types
    3. Apply transformation-specific compatibility rules
    """

    def validate(
        self,
        source_schema: _Optional[StepOutputSchema],
        target_schema: _Optional[SkillInputSchema],
        binding_spec: _Optional[ParamBindingSpec],
    ) -> ValidationResult:
        """Validate inter-step type compatibility.

        Returns a ValidationResult with one of four levels:
        - COMPATIBLE: natively compatible, no transformation needed
        - ADAPTER_COMPATIBLE: compatible via normalized envelope adapter
        - INCOMPATIBLE: types are incompatible
        - UNKNOWN: cannot determine (always carries UnknownReasonCode)
        """
        # --- UNKNOWN checks: missing inputs ---
        if binding_spec is None:
            return ValidationResult(
                level=CompatibilityLevel.UNKNOWN,
                unknown_reason=UnknownReasonCode.BINDING_MISSING,
                message="ParamBindingSpec is missing",
            )

        if source_schema is None:
            return ValidationResult(
                level=CompatibilityLevel.UNKNOWN,
                source_node_id=binding_spec.source_node_id,
                source_field=binding_spec.source_field,
                target_param=binding_spec.target_param,
                unknown_reason=UnknownReasonCode.SOURCE_SCHEMA_MISSING,
                message="Source StepOutputSchema is missing",
            )

        if target_schema is None:
            return ValidationResult(
                level=CompatibilityLevel.UNKNOWN,
                source_node_id=binding_spec.source_node_id,
                source_field=binding_spec.source_field,
                target_param=binding_spec.target_param,
                unknown_reason=UnknownReasonCode.TARGET_SCHEMA_MISSING,
                message="Target SkillInputSchema is missing",
            )

        # --- Resolve source field type ---
        source_field_schema = _find_field(source_schema, binding_spec.source_field)
        if source_field_schema is None:
            return ValidationResult(
                level=CompatibilityLevel.UNKNOWN,
                source_node_id=binding_spec.source_node_id,
                source_field=binding_spec.source_field,
                target_param=binding_spec.target_param,
                unknown_reason=UnknownReasonCode.PROJECTED_FIELD_NOT_FOUND,
                message=f"Field '{binding_spec.source_field}' not found in source schema",
            )

        # --- Resolve target param type ---
        target_param_spec = _find_param(target_schema, binding_spec.target_param)
        if target_param_spec is None:
            return ValidationResult(
                level=CompatibilityLevel.UNKNOWN,
                source_node_id=binding_spec.source_node_id,
                source_field=binding_spec.source_field,
                source_type=source_field_schema.field_type,
                target_param=binding_spec.target_param,
                unknown_reason=UnknownReasonCode.TARGET_SCHEMA_MISSING,
                message=f"Param '{binding_spec.target_param}' not found in target schema",
            )

        source_type = source_field_schema.field_type
        target_type = target_param_spec.expected_python_type

        # --- Transformation-specific validation ---
        transformation = binding_spec.transformation_kind

        if transformation == TransformationKind.IDENTITY:
            return self._validate_identity(binding_spec, source_type, target_type)

        if transformation == TransformationKind.NORMALIZED_ENVELOPE:
            return self._validate_envelope(
                binding_spec, source_type, target_type, target_param_spec,
            )

        # Unrecognized transformation kind
        return ValidationResult(
            level=CompatibilityLevel.UNKNOWN,
            source_node_id=binding_spec.source_node_id,
            source_field=binding_spec.source_field,
            source_type=source_type,
            target_param=binding_spec.target_param,
            target_expected_type=target_type,
            transformation_kind=transformation,
            unknown_reason=UnknownReasonCode.TRANSFORMATION_UNRESOLVABLE,
            message=f"Unrecognized transformation kind: {transformation}",
        )

    # ------------------------------------------------------------------
    # IDENTITY path
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_identity(
        binding: ParamBindingSpec,
        source_type: str,
        target_type: str,
    ) -> ValidationResult:
        if source_type == target_type:
            return ValidationResult(
                level=CompatibilityLevel.COMPATIBLE,
                source_node_id=binding.source_node_id,
                source_field=binding.source_field,
                source_type=source_type,
                target_param=binding.target_param,
                target_expected_type=target_type,
                transformation_kind=TransformationKind.IDENTITY,
                message="Types match (identity)",
            )
        return ValidationResult(
            level=CompatibilityLevel.INCOMPATIBLE,
            source_node_id=binding.source_node_id,
            source_field=binding.source_field,
            source_type=source_type,
            target_param=binding.target_param,
            target_expected_type=target_type,
            transformation_kind=TransformationKind.IDENTITY,
            message=f"Type mismatch: source={source_type}, target={target_type}",
        )

    # ------------------------------------------------------------------
    # NORMALIZED_ENVELOPE path
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_envelope(
        binding: ParamBindingSpec,
        source_type: str,
        target_type: str,
        target_param_spec: ParameterSpec,
    ) -> ValidationResult:
        if not target_param_spec.accepts_envelope:
            return ValidationResult(
                level=CompatibilityLevel.INCOMPATIBLE,
                source_node_id=binding.source_node_id,
                source_field=binding.source_field,
                source_type=source_type,
                target_param=binding.target_param,
                target_expected_type=target_type,
                transformation_kind=TransformationKind.NORMALIZED_ENVELOPE,
                message=f"Target param '{binding.target_param}' does not accept envelope",
            )

        # dict source → already compatible, no wrapping needed
        if source_type == "dict":
            return ValidationResult(
                level=CompatibilityLevel.COMPATIBLE,
                source_node_id=binding.source_node_id,
                source_field=binding.source_field,
                source_type=source_type,
                target_param=binding.target_param,
                target_expected_type=target_type,
                transformation_kind=TransformationKind.NORMALIZED_ENVELOPE,
                message="Source is dict, no envelope wrapping needed",
            )

        # str/int/list/etc → adapter compatible via envelope wrapping
        return ValidationResult(
            level=CompatibilityLevel.ADAPTER_COMPATIBLE,
            source_node_id=binding.source_node_id,
            source_field=binding.source_field,
            source_type=source_type,
            target_param=binding.target_param,
            target_expected_type=target_type,
            transformation_kind=TransformationKind.NORMALIZED_ENVELOPE,
            adapter_name="envelope_wrapper",
            message=f"Envelope wrapping: {source_type} → dict",
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _find_field(
    schema: StepOutputSchema, field_name: str,
) -> _Optional[FieldSchema]:
    """Find a FieldSchema by name in a StepOutputSchema."""
    for f in schema.fields:
        if f.field_name == field_name:
            return f
    return None


def _find_param(
    schema: SkillInputSchema, param_name: str,
) -> _Optional[ParameterSpec]:
    """Find a ParameterSpec by name in a SkillInputSchema."""
    for p in schema.params:
        if p.param_name == param_name:
            return p
    return None
