"""
Core schema data models for the graph type system.

Provides dual-layer output schema (semantic ValueKind + structural FieldSchema),
skill input parameter schema, and parameter binding specifications.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ValueKind(str, Enum):
    """Semantic layer: content type of a step output."""
    TEXT = "text"
    JSON = "json"
    TABLE = "table"
    BINARY = "binary"
    PATH = "path"


class TransformationKind(str, Enum):
    """Binding transformation type."""
    IDENTITY = "identity"                        # pass-through
    NORMALIZED_ENVELOPE = "normalized_envelope"  # envelope wrap (str → {"result": value})


# ---------------------------------------------------------------------------
# Output schema (Requirement 1)
# ---------------------------------------------------------------------------


@dataclass
class FieldSchema:
    """
    Structural layer: canonical projected shape of a single field.

    This is a *schema projection* — it does NOT mandate the in-memory shape.
    For example, a TEXT output may declare ``{result: str}`` meaning
    "when structured access is needed, the value is reachable via the
    ``result`` field", without requiring the raw output to be a dict.
    """
    field_name: str
    field_type: str  # "str", "dict", "list", "int", "float", "bool"
    optional: bool = False


@dataclass
class StepOutputSchema:
    """
    Dual-layer output schema: semantic layer (ValueKind) + structural layer
    (FieldSchema list).
    """
    semantic_kind: ValueKind
    fields: List[FieldSchema] = field(default_factory=list)
    schema_version: str = "1.0.0"


# ---------------------------------------------------------------------------
# Input schema & parameter binding (Requirement 2)
# ---------------------------------------------------------------------------


@dataclass
class ParameterSpec:
    """Type declaration for a single skill input parameter."""
    param_name: str
    expected_kind: ValueKind
    expected_python_type: str  # "str", "dict", "list"
    accepts_envelope: bool = False


@dataclass
class SkillInputSchema:
    """
    Aggregated input parameter schema for a skill.

    Grouped per-skill for registry caching, auto-inference, debug display,
    and ``StepNode.metadata["input_schema"]`` storage.
    """
    skill_name: str
    params: List[ParameterSpec] = field(default_factory=list)
    schema_version: str = "1.0.0"


@dataclass
class ParamBindingSpec:
    """
    Parameter binding specification: explicit binding path on a DataEdge
    describing inter-step data flow.
    """
    source_node_id: str
    source_field: str       # specific field name in the source node output
    target_param: str       # specific parameter name in the target node
    transformation_kind: TransformationKind = TransformationKind.IDENTITY
    binding_id: str = ""    # auto-generated: {source_node_id}.{source_field}->{target_param}
    schema_version: str = "1.0.0"
