"""
Normalization record data model.

Explicit runtime artifact recording each normalization operation
performed during inter-step data injection.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NormalizationRecord:
    """
    Explicit runtime artifact: records a single normalization operation.

    Each record is precisely associated with the binding context that
    triggered it (which edge, which target_param), so debugging
    "why was this value envelope-wrapped?" never requires tracing back
    to edge definitions.
    """
    source_node_id: str
    original_type: str            # original Python type name
    normalized_type: str = "dict" # always "dict" after envelope wrapping
    adapter_name: str = "envelope_wrapper"
    target_skill: str = ""
    target_param: str = ""        # precise to parameter level
    binding_id: str = ""          # associated ParamBindingSpec identifier
    timestamp: float = 0.0
    schema_version: str = "1.0.0"
