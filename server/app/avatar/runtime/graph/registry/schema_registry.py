"""
SchemaRegistry — unified schema lookup for StepOutputSchema and SkillInputSchema.

All schema queries MUST go through this registry. Adapters, validators, and
executors are forbidden from maintaining their own schema declarations.

Features:
- Pre-registered output/input schemas for known skills
- Auto-inference from Pydantic input_model for unregistered skills (cached)
- Deprecation warning emitted once per skill for auto-inferred schemas
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Set

from app.avatar.runtime.graph.types.schema import (
    FieldSchema,
    ParameterSpec,
    SkillInputSchema,
    StepOutputSchema,
    ValueKind,
)

logger = logging.getLogger(__name__)


class SchemaRegistry:
    """Singleton-style registry for step output and skill input schemas.

    Usage::

        registry = SchemaRegistry()
        # Pre-registered schemas are available immediately
        schema = registry.get_output_schema("llm.fallback")

        # Register custom schemas
        registry.register_output_schema("my.skill", my_schema)

        # Auto-inference for unregistered skills (cached + deprecation warning)
        schema = registry.get_input_schema_or_infer("unknown.skill", input_model)
    """

    def __init__(self) -> None:
        self._output_schemas: Dict[str, StepOutputSchema] = {}
        self._input_schemas: Dict[str, SkillInputSchema] = {}
        self._inferred_cache: Dict[str, SkillInputSchema] = {}
        self._deprecation_warned: Set[str] = set()
        self._register_defaults()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_output_schema(self, skill_name: str) -> Optional[StepOutputSchema]:
        """Return the registered output schema for *skill_name*, or None."""
        return self._output_schemas.get(skill_name)

    def get_input_schema(self, skill_name: str) -> Optional[SkillInputSchema]:
        """Return the registered input schema for *skill_name*, or None."""
        return self._input_schemas.get(skill_name)

    def register_output_schema(self, skill_name: str, schema: StepOutputSchema) -> None:
        """Register (or overwrite) an output schema for *skill_name*."""
        self._output_schemas[skill_name] = schema

    def register_input_schema(self, skill_name: str, schema: SkillInputSchema) -> None:
        """Register (or overwrite) an input schema for *skill_name*."""
        self._input_schemas[skill_name] = schema

    def get_input_schema_or_infer(
        self,
        skill_name: str,
        input_model: Any = None,
    ) -> Optional[SkillInputSchema]:
        """Return input schema — registered, cached-inferred, or freshly inferred.

        If *skill_name* is not registered and *input_model* is a Pydantic
        model class, the schema is inferred via reflection, cached in the
        registry, and a deprecation warning is emitted (once per skill).

        Returns None only when no registered schema exists AND inference
        is not possible (no input_model or not a Pydantic model).
        """
        # 1. Check registered schemas first
        registered = self._input_schemas.get(skill_name)
        if registered is not None:
            return registered

        # 2. Check inference cache
        cached = self._inferred_cache.get(skill_name)
        if cached is not None:
            return cached

        # 3. Attempt auto-inference from Pydantic model
        if input_model is None:
            return None

        inferred = self._infer_from_pydantic(skill_name, input_model)
        if inferred is None:
            return None

        # Cache the inferred schema
        self._inferred_cache[skill_name] = inferred

        # Deprecation warning — once per skill
        if skill_name not in self._deprecation_warned:
            self._deprecation_warned.add(skill_name)
            logger.warning(
                "SkillInputSchema for '%s' was auto-inferred from Pydantic model. "
                "Register an explicit schema via SchemaRegistry.register_input_schema() "
                "to suppress this warning.",
                skill_name,
            )

        return inferred

    # ------------------------------------------------------------------
    # Pre-registered defaults
    # ------------------------------------------------------------------

    def _register_defaults(self) -> None:
        """Populate pre-registered output and input schemas for known skills."""
        # --- Output schemas (Requirement 1) ---
        self._output_schemas.update({
            "llm.fallback": StepOutputSchema(
                semantic_kind=ValueKind.TEXT,
                fields=[FieldSchema("result", "str")],
            ),
            "python.run": StepOutputSchema(
                semantic_kind=ValueKind.JSON,
                fields=[],  # dynamic — inferred at runtime
            ),
            "fs.write": StepOutputSchema(
                semantic_kind=ValueKind.PATH,
                fields=[FieldSchema("path", "str")],
            ),
            "fs.read": StepOutputSchema(
                semantic_kind=ValueKind.TEXT,
                fields=[FieldSchema("content", "str")],
            ),
            "json.parse": StepOutputSchema(
                semantic_kind=ValueKind.JSON,
                fields=[],  # dynamic
            ),
            "table.render": StepOutputSchema(
                semantic_kind=ValueKind.TABLE,
                fields=[FieldSchema("rows", "list")],
            ),
        })

        # --- Input schemas (Requirement 2) ---
        self._input_schemas.update({
            "fs.write": SkillInputSchema("fs.write", [
                ParameterSpec("content", ValueKind.TEXT, "str"),
                ParameterSpec("path", ValueKind.PATH, "str"),
            ]),
            "python.run": SkillInputSchema("python.run", [
                ParameterSpec("inputs", ValueKind.JSON, "dict", accepts_envelope=True),
            ]),
            "llm.fallback": SkillInputSchema("llm.fallback", [
                ParameterSpec("prompt", ValueKind.TEXT, "str"),
            ]),
            "json.parse": SkillInputSchema("json.parse", [
                ParameterSpec("text", ValueKind.TEXT, "str"),
            ]),
            "table.render": SkillInputSchema("table.render", [
                ParameterSpec("rows", ValueKind.TABLE, "list"),
            ]),
        })

    # ------------------------------------------------------------------
    # Auto-inference from Pydantic model
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_from_pydantic(skill_name: str, input_model: Any) -> Optional[SkillInputSchema]:
        """Attempt to infer SkillInputSchema from a Pydantic model class.

        Returns None if *input_model* is not a recognizable Pydantic model.
        """
        # Support both Pydantic v1 (model_fields via __fields__) and v2 (model_fields)
        fields: Optional[dict] = None
        if hasattr(input_model, "model_fields"):
            # Pydantic v2
            fields = input_model.model_fields
        elif hasattr(input_model, "__fields__"):
            # Pydantic v1
            fields = input_model.__fields__
        else:
            return None

        params = []
        for name, field_info in fields.items():
            python_type = _resolve_python_type(field_info)
            kind = _python_type_to_value_kind(python_type)
            params.append(ParameterSpec(
                param_name=name,
                expected_kind=kind,
                expected_python_type=python_type,
            ))

        return SkillInputSchema(skill_name=skill_name, params=params)


# ---------------------------------------------------------------------------
# Module-level helpers for Pydantic reflection
# ---------------------------------------------------------------------------

def _resolve_python_type(field_info: Any) -> str:
    """Best-effort extraction of the Python type name from a Pydantic field."""
    # Pydantic v2: field_info.annotation
    annotation = getattr(field_info, "annotation", None)
    if annotation is not None:
        return _annotation_to_str(annotation)
    # Pydantic v1: field_info.outer_type_
    outer = getattr(field_info, "outer_type_", None)
    if outer is not None:
        return _annotation_to_str(outer)
    return "str"  # safe fallback


def _annotation_to_str(annotation: Any) -> str:
    """Convert a type annotation to a simple string label."""
    origin = getattr(annotation, "__origin__", None)
    if origin is list or (isinstance(origin, type) and issubclass(origin, list)):
        return "list"
    if origin is dict or (isinstance(origin, type) and issubclass(origin, dict)):
        return "dict"
    if isinstance(annotation, type):
        name = annotation.__name__
        mapping = {"str": "str", "int": "int", "float": "float", "bool": "bool",
                   "dict": "dict", "list": "list"}
        return mapping.get(name, "str")
    return "str"


def _python_type_to_value_kind(python_type: str) -> ValueKind:
    """Map a simple Python type string to a ValueKind."""
    mapping = {
        "dict": ValueKind.JSON,
        "list": ValueKind.TABLE,
        "int": ValueKind.JSON,
        "float": ValueKind.JSON,
        "bool": ValueKind.JSON,
    }
    return mapping.get(python_type, ValueKind.TEXT)
