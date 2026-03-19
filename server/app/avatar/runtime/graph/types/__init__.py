"""
Graph type system — core data models for inter-step type validation,
normalization, error classification, and planning hints.

Re-exports all public types for convenient access.
"""

from .schema import (
    FieldSchema,
    ParamBindingSpec,
    ParameterSpec,
    SkillInputSchema,
    StepOutputSchema,
    TransformationKind,
    ValueKind,
)
from .validation import (
    CompatibilityLevel,
    InterStepTypeValidator,
    UnknownReasonCode,
    ValidationResult,
)
from .normalization import NormalizationRecord
from .error_classification import (
    ErrorClassification,
    ErrorClassifier,
    ErrorCode,
    RecoveryResult,
    RuntimeErrorClass,
)
from .planning_hint import PlanningHint

__all__ = [
    # schema.py
    "ValueKind",
    "FieldSchema",
    "StepOutputSchema",
    "TransformationKind",
    "ParameterSpec",
    "SkillInputSchema",
    "ParamBindingSpec",
    # validation.py
    "CompatibilityLevel",
    "InterStepTypeValidator",
    "UnknownReasonCode",
    "ValidationResult",
    # normalization.py
    "NormalizationRecord",
    # error_classification.py
    "RuntimeErrorClass",
    "ErrorCode",
    "ErrorClassification",
    "ErrorClassifier",
    "RecoveryResult",
    # planning_hint.py
    "PlanningHint",
]
