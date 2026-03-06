"""
GraphExecutor - Node Execution with Parameter Resolution

Requirements: 5.1, 5.2, 5.3, 5.7, 5.8, 7.2, 7.5, 7.6, 7.7
"""

from __future__ import annotations
from typing import Dict, List, Any, Optional, TYPE_CHECKING
import json
import logging
from datetime import datetime

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.graph.models.step_node import StepNode
    from app.avatar.runtime.graph.models.data_edge import DataEdge
    from app.avatar.runtime.graph.storage.artifact_store import ArtifactStore
    from app.avatar.runtime.graph.context.execution_context import ExecutionContext

ARTIFACT_SIZE_THRESHOLD = 1 * 1024 * 1024

logger = logging.getLogger(__name__)


class ExecutionError(Exception):
    pass

class ParameterResolutionError(ExecutionError):
    pass

class TransformerError(ExecutionError):
    pass


class GraphExecutor:
    """
    Executor for graph nodes with parameter resolution via DataEdge traversal.
    Uses skill_registry directly — no capability_registry dependency.
    """

    def __init__(
        self,
        transformer_registry: Optional[Dict[str, Any]] = None,
        artifact_store: Optional['ArtifactStore'] = None,
        granted_permissions: Optional[List[str]] = None,
        base_path: Optional[Any] = None,
        memory_manager: Optional[Any] = None,
        # Legacy params kept for backward compat during transition
        capability_registry: Optional[Any] = None,
        type_registry: Optional[Any] = None,
    ):
        self.transformer_registry = transformer_registry or {}
        self.artifact_store = artifact_store
        self.granted_permissions: List[str] = granted_permissions or []
        self.base_path = base_path
        self.memory_manager = memory_manager
        logger.info("GraphExecutor initialized")

    async def execute_node(
        self,
        graph: 'ExecutionGraph',
        node: 'StepNode',
        context: Optional['ExecutionContext'] = None,
    ) -> None:
        logger.info(f"[GraphExecutor] Executing node {node.id} (skill: {node.capability_name})")
        start_time = datetime.now()

        try:
            node.mark_running()

            resolved_params = self._resolve_parameters(graph, node, context)
            final_params = {**node.params, **resolved_params}

            outputs = await self._execute_skill(node.capability_name, final_params)

            end_time = datetime.now()
            latency = (end_time - start_time).total_seconds()

            if node.metadata is None:
                node.metadata = {}
            node.metadata["execution_latency"] = latency

            if context:
                current_cost = context.variables.get("accumulated_cost", 0.0)
                context.variables.set("accumulated_cost", current_cost)

            if self.artifact_store:
                outputs = await self._offload_large_outputs(outputs, node.id, context)

            if context:
                context.set_node_output(node.id, outputs)
            node.mark_success(outputs)

            logger.info(f"[GraphExecutor] Node {node.id} completed in {latency:.3f}s")

        except Exception as e:
            end_time = datetime.now()
            latency = (end_time - start_time).total_seconds()
            if node.metadata is None:
                node.metadata = {}
            node.metadata["execution_latency"] = latency
            node.mark_failed(f"Execution failed: {str(e)}")
            logger.error(f"[GraphExecutor] Node {node.id} failed: {e}", exc_info=True)

    def _resolve_parameters(
        self,
        graph: 'ExecutionGraph',
        node: 'StepNode',
        context: Optional['ExecutionContext'] = None,
    ) -> Dict[str, Any]:
        resolved: Dict[str, Any] = {}
        incoming = graph.get_incoming_edges(node.id)
        if not incoming:
            return resolved

        edges_by_param: Dict[str, List['DataEdge']] = {}
        for edge in incoming:
            edges_by_param.setdefault(edge.target_param, []).append(edge)

        for target_param, edges in edges_by_param.items():
            try:
                if len(edges) == 1:
                    resolved[target_param] = self._resolve_single_edge(graph, edges[0], context)
                else:
                    resolved[target_param] = self._merge_multiple_edges(graph, edges, context)
            except Exception as e:
                raise ParameterResolutionError(
                    f"Failed to resolve '{target_param}' for node {node.id}: {e}"
                )

        return resolved

    def _resolve_single_edge(
        self,
        graph: 'ExecutionGraph',
        edge: 'DataEdge',
        context: Optional['ExecutionContext'] = None,
    ) -> Any:
        source_node = graph.nodes.get(edge.source_node)
        if source_node is None:
            raise ParameterResolutionError(f"Source node '{edge.source_node}' not found")

        if source_node.status.value != "success":
            raise ParameterResolutionError(
                f"Source node '{edge.source_node}' not completed (status: {source_node.status.value})"
            )

        if context:
            node_outputs = context.get_node_output(edge.source_node)
            if node_outputs and edge.source_field in node_outputs:
                value = node_outputs[edge.source_field]
            elif edge.source_field in source_node.outputs:
                value = source_node.outputs[edge.source_field]
            else:
                raise ParameterResolutionError(
                    f"Field '{edge.source_field}' not found in '{edge.source_node}' outputs. "
                    f"Available: {list(source_node.outputs.keys())}"
                )
        else:
            if edge.source_field not in source_node.outputs:
                raise ParameterResolutionError(
                    f"Field '{edge.source_field}' not found in '{edge.source_node}' outputs"
                )
            value = source_node.outputs[edge.source_field]

        if edge.transformer_name:
            value = self._apply_transformer(edge.transformer_name, value, edge)

        return value

    def _apply_transformer(self, transformer_name: str, value: Any, edge: 'DataEdge') -> Any:
        if transformer_name not in self.transformer_registry:
            raise TransformerError(f"Unknown transformer '{transformer_name}'")
        try:
            return self.transformer_registry[transformer_name](value)
        except Exception as e:
            raise TransformerError(f"Transformer '{transformer_name}' failed: {e}")

    def _merge_multiple_edges(
        self,
        graph: 'ExecutionGraph',
        edges: List['DataEdge'],
        context: Optional['ExecutionContext'] = None,
    ) -> Any:
        values = [self._resolve_single_edge(graph, e, context) for e in edges]
        first = values[0]

        if isinstance(first, list):
            result = []
            for v in values:
                result.extend(v) if isinstance(v, list) else result.append(v)
            return result
        elif isinstance(first, dict):
            result = {}
            for v in values:
                if isinstance(v, dict):
                    result.update(v)
            return result
        else:
            return values[-1]

    async def _execute_skill(self, skill_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a skill directly via skill_registry.
        Supports both direct skill names (e.g. 'fs.read') and
        legacy capability names that map to a single skill.
        """
        from app.avatar.skills.registry import skill_registry
        from app.avatar.runtime.executor.factory import ExecutorFactory
        from app.avatar.skills.context import SkillContext
        from pathlib import Path

        skill_cls = skill_registry.get(skill_name)

        if skill_cls is None:
            raise ExecutionError(
                f"Skill '{skill_name}' not found in registry. "
                f"Available: {list(skill_registry._skills.keys())}"
            )

        base_path = Path(self.base_path) if self.base_path else Path(".")
        ctx = SkillContext(
            base_path=base_path,
            dry_run=False,
            memory_manager=self.memory_manager,
        )

        try:
            input_obj = skill_cls.spec.input_model(**params)
        except Exception as e:
            raise ExecutionError(f"Invalid parameters for skill '{skill_name}': {e}")

        executor = ExecutorFactory.get_executor(skill_cls)
        skill_instance = skill_cls()
        result = await executor.execute(skill_instance, input_obj, ctx)

        if hasattr(result, "model_dump"):
            return result.model_dump()
        elif isinstance(result, dict):
            return result
        else:
            return {"output": str(result), "success": True}

    # Keep _execute_sequential for backward compat with existing tests
    async def _execute_sequential(self, capability_or_skill, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Backward-compatible sequential execution.
        Accepts either a Capability object (legacy) or a skill name string.
        """
        # If it's a legacy Capability object with composed_skills
        if hasattr(capability_or_skill, "composed_skills"):
            from app.avatar.skills.registry import skill_registry
            from app.avatar.runtime.executor.factory import ExecutorFactory
            from app.avatar.skills.context import SkillContext
            from pathlib import Path

            aggregated: Dict[str, Any] = {}
            current_params = dict(params)

            for skill_name in capability_or_skill.composed_skills:
                skill_cls = skill_registry.get(skill_name)
                if skill_cls is None:
                    raise ExecutionError(
                        f"Skill '{skill_name}' not found (required by '{capability_or_skill.name}')"
                    )

                base_path = Path(self.base_path) if self.base_path else Path(".")
                ctx = SkillContext(base_path=base_path, dry_run=False, memory_manager=self.memory_manager)

                try:
                    input_obj = skill_cls.spec.input_model(**current_params)
                except Exception as e:
                    raise ExecutionError(f"Invalid parameters for skill '{skill_name}': {e}")

                executor = ExecutorFactory.get_executor(skill_cls)
                result = await executor.execute(skill_cls(), input_obj, ctx)

                result_dict = result.model_dump() if hasattr(result, "model_dump") else (result if isinstance(result, dict) else {"output": str(result), "success": True})
                aggregated.update(result_dict)

                if "output" in result_dict:
                    current_params["input"] = result_dict["output"]

            return aggregated

        # Otherwise treat as skill name string
        return await self._execute_skill(str(capability_or_skill), params)

    async def _offload_large_outputs(
        self,
        outputs: Dict[str, Any],
        node_id: str,
        context: Optional['ExecutionContext'] = None,
    ) -> Dict[str, Any]:
        from app.avatar.runtime.graph.storage.artifact_store import ArtifactType

        result = {}
        for field, value in outputs.items():
            try:
                serialized = json.dumps(value, default=str).encode("utf-8")
                if len(serialized) > ARTIFACT_SIZE_THRESHOLD:
                    artifact = await self.artifact_store.store(
                        data=serialized,
                        artifact_type=ArtifactType.DATASET,
                        created_by_node=node_id,
                        metadata={"field": field, "original_type": type(value).__name__},
                    )
                    result[field] = {"__artifact_id__": artifact.id}
                    if context:
                        context.set_artifact(artifact.id, artifact.model_dump())
                else:
                    result[field] = value
            except Exception as e:
                logger.warning(f"[GraphExecutor] Failed to check/offload field '{field}': {e}")
                result[field] = value

        return result
