"""
Edge management mixin for GraphController.

Handles patch application, edge type validation, binding spec inference,
implicit edge injection, and primary output field inference.

Extracted from graph_controller.py to keep the controller focused on
orchestration logic.
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional, TYPE_CHECKING
import re
import logging

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.graph.models.step_node import StepNode
    from app.avatar.runtime.graph.models.graph_patch import GraphPatch
    from app.avatar.runtime.graph.controller.persistence.long_task_helpers import LongTaskContext

logger = logging.getLogger(__name__)


class EdgeManagerMixin:
    """Mixin providing edge management methods for GraphController."""

    _STEP_REF_PATTERN = re.compile(r'step_(\d+)_output')

    # Ordered priority list for resolving the "primary output" field of a skill.
    _PRIMARY_OUTPUT_FIELDS = ("output", "result", "content", "stdout")

    def _apply_patch(
        self,
        patch: 'GraphPatch',
        graph: 'ExecutionGraph',
        lt_ctx: Optional['LongTaskContext'] = None,
        env_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        from app.avatar.runtime.graph.models.graph_patch import PatchOperation

        # Phase 1: Apply ADD_NODE first so all node IDs exist before edges
        # are validated.  Planner output order is not guaranteed to place
        # ADD_NODE before ADD_EDGE referencing that node.
        deferred_edges: list = []
        other_actions: list = []

        for action in patch.actions:
            if action.operation == PatchOperation.ADD_NODE and action.node:
                graph.add_node(action.node)
                logger.debug(f"Added node: {action.node.id}")
                self._inject_implicit_edges(action.node, graph)
                if lt_ctx is not None:
                    lt_ctx.graph_version += 1
                    self._lt_record_patch(lt_ctx, action, graph)
            elif action.operation == PatchOperation.ADD_EDGE and action.edge:
                deferred_edges.append(action)
            else:
                other_actions.append(action)

        # Phase 2: Apply ADD_EDGE (all nodes now registered)
        for action in deferred_edges:
            self._validate_edge_types(action.edge, graph, env_context)
            self._ensure_binding_spec(action.edge, graph)
            graph.add_edge(action.edge)
            logger.debug(f"Added edge: {action.edge.source_node} → {action.edge.target_node}")
            if lt_ctx is not None:
                lt_ctx.graph_version += 1
                self._lt_record_patch(lt_ctx, action, graph)

        # Phase 3: Apply remaining actions (REMOVE_NODE, REMOVE_EDGE, FINISH)
        for action in other_actions:
            if action.operation == PatchOperation.REMOVE_NODE and action.node_id:
                if action.node_id in graph.nodes:
                    del graph.nodes[action.node_id]
                    logger.debug(f"Removed node: {action.node_id}")
            elif action.operation == PatchOperation.REMOVE_EDGE and action.edge_id:
                if action.edge_id in graph.edges:
                    del graph.edges[action.edge_id]
                    logger.debug(f"Removed edge: {action.edge_id}")
            elif action.operation == PatchOperation.FINISH:
                logger.debug("FINISH operation in patch")

            if lt_ctx is not None and action.operation != PatchOperation.FINISH:
                lt_ctx.graph_version += 1
                self._lt_record_patch(lt_ctx, action, graph)

        logger.info(
            f"Applied patch: {len(patch.actions)} actions, "
            f"graph now has {len(graph.nodes)} nodes, {len(graph.edges)} edges"
        )

    def _validate_edge_types(self, edge: Any, graph: 'ExecutionGraph', env_context: Optional[Dict[str, Any]] = None) -> None:
        """Run InterStepTypeValidator on an edge. INCOMPATIBLE → inject type_mismatch_hint."""
        try:
            from app.avatar.runtime.graph.types.validation import InterStepTypeValidator
            from app.avatar.runtime.graph.registry.schema_registry import SchemaRegistry

            source_node = graph.nodes.get(edge.source_node)
            target_node = graph.nodes.get(edge.target_node)
            if source_node is None or target_node is None:
                return

            registry = SchemaRegistry()
            source_schema = (source_node.metadata or {}).get("output_schema")
            if source_schema and isinstance(source_schema, dict):
                from app.avatar.runtime.graph.types.schema import StepOutputSchema, ValueKind, FieldSchema
                source_schema = StepOutputSchema(
                    semantic_kind=ValueKind(source_schema.get("semantic_kind", "text")),
                    fields=[FieldSchema(**f) for f in source_schema.get("fields", [])],
                )
            else:
                source_schema = registry.get_output_schema(source_node.capability_name)

            target_schema = registry.get_input_schema(target_node.capability_name)

            binding_spec = getattr(edge, "binding_spec", None)
            if binding_spec is None:
                return

            validator = InterStepTypeValidator()
            result = validator.validate(source_schema, target_schema, binding_spec)

            from app.avatar.runtime.graph.types.validation import CompatibilityLevel
            if result.level == CompatibilityLevel.INCOMPATIBLE and env_context is not None:
                env_context["type_mismatch_hint"] = {
                    "source_node": edge.source_node,
                    "source_field": result.source_field,
                    "source_type": result.source_type,
                    "target_param": result.target_param,
                    "target_expected_type": result.target_expected_type,
                    "message": result.message,
                }
                logger.warning(f"[TypeValidator] INCOMPATIBLE: {result.message}")
            elif result.level == CompatibilityLevel.ADAPTER_COMPATIBLE:
                logger.debug(f"[TypeValidator] ADAPTER_COMPATIBLE: {result.message}")
        except Exception as _tv_err:
            logger.debug(f"[TypeValidator] Validation skipped: {_tv_err}")

    def _ensure_binding_spec(self, edge: Any, graph: 'ExecutionGraph') -> None:
        """Auto-infer ParamBindingSpec on edge if missing (18.B2)."""
        try:
            if getattr(edge, "binding_spec", None) is not None:
                return

            source_node = graph.nodes.get(edge.source_node)
            if source_node is None:
                return

            from app.avatar.runtime.graph.types.schema import ParamBindingSpec, TransformationKind
            from app.avatar.runtime.graph.registry.schema_registry import SchemaRegistry

            registry = SchemaRegistry()
            source_schema = registry.get_output_schema(source_node.capability_name)
            target_schema = registry.get_input_schema(edge.target_node if isinstance(edge.target_node, str) else "")

            source_field = edge.source_field or "result"

            transformation = TransformationKind.IDENTITY
            if target_schema and source_schema:
                for param in target_schema.params:
                    if param.param_name == edge.target_param and param.accepts_envelope:
                        if source_schema.semantic_kind.value in ("text", "path"):
                            transformation = TransformationKind.NORMALIZED_ENVELOPE
                        break

            edge.binding_spec = ParamBindingSpec(
                source_node_id=edge.source_node,
                source_field=source_field,
                target_param=edge.target_param or "",
                transformation_kind=transformation,
                binding_id=f"{edge.source_node}.{source_field}->{edge.target_param or ''}",
            )
        except Exception as _bs_err:
            logger.debug(f"[BindingSpec] Auto-infer skipped: {_bs_err}")

    @staticmethod
    def _infer_primary_output_field(source_node: 'StepNode') -> str:
        """
        Infer the best source_field for an AutoEdge by inspecting the source
        node's skill output_model via the registry.
        """
        # --- Phase 1: static schema inspection ---
        try:
            from app.avatar.skills.registry import skill_registry
            skill_cls = skill_registry.get(source_node.capability_name)
            if skill_cls is not None:
                model_fields = set(skill_cls.spec.output_model.model_fields.keys())
                for candidate in EdgeManagerMixin._PRIMARY_OUTPUT_FIELDS:
                    if candidate in model_fields:
                        return candidate
        except Exception:
            pass

        # --- Phase 2: runtime outputs (node already completed) ---
        if source_node.outputs:
            for candidate in EdgeManagerMixin._PRIMARY_OUTPUT_FIELDS:
                if candidate in source_node.outputs:
                    return candidate

        # --- Phase 3: convention fallback ---
        return "output"

    def _inject_implicit_edges(self, node: 'StepNode', graph: 'ExecutionGraph') -> None:
        """Scan node params for step_N_output references and add data edges."""
        if not node.params:
            return
        try:
            from app.avatar.runtime.graph.models.data_edge import DataEdge

            skip_params: set = set()
            try:
                from app.avatar.skills.registry import skill_registry
                skill_cls = skill_registry.get(node.capability_name)
                if skill_cls is not None:
                    skip_params = skill_cls.spec.code_params
            except Exception:
                pass

            for param_name, param_value in node.params.items():
                if param_name in skip_params:
                    continue
                if not isinstance(param_value, str):
                    continue
                for match in self._STEP_REF_PATTERN.finditer(param_value):
                    source_node_id = f"step_{match.group(1)}"
                    source_node = graph.nodes.get(source_node_id)
                    if source_node is None:
                        continue
                    existing = any(
                        e.source_node == source_node_id and
                        e.target_node == node.id and
                        e.target_param == param_name
                        for e in graph.edges.values()
                    )
                    if existing:
                        continue
                    source_field = self._infer_primary_output_field(source_node)
                    edge = DataEdge(
                        source_node=source_node_id,
                        source_field=source_field,
                        target_node=node.id,
                        target_param=param_name,
                    )
                    graph.add_edge(edge)
                    logger.info(f"[AutoEdge] {source_node_id} → {node.id}.{param_name} (field={source_field})")
        except Exception as e:
            logger.debug(f"[AutoEdge] Failed for {node.id}: {e}")
