"""
Parameter resolution mixin for GraphExecutor.

Handles resolving parameters from upstream node outputs via DataEdge
traversal and transformer application.

Extracted from graph_executor.py to keep the executor module focused on
core execution logic.
"""

from __future__ import annotations
import json as _json
from typing import Dict, List, Any, Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.graph.models.step_node import StepNode
    from app.avatar.runtime.graph.models.data_edge import DataEdge
    from app.avatar.runtime.graph.context.execution_context import ExecutionContext

logger = logging.getLogger(__name__)


class ParameterResolutionError(Exception):
    """Failed to resolve a parameter from upstream edges."""
    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class TransformerError(Exception):
    """Transformer application failure."""
    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class ParameterResolverMixin:
    """Mixin providing parameter resolution methods for GraphExecutor."""

    # Fallback priority for resolving primary output field.
    # Must stay in sync with GraphController._PRIMARY_OUTPUT_FIELDS and
    # _inject_node_outputs_into_code value extraction chain.
    _PRIMARY_OUTPUT_FALLBACKS = ("output", "result", "content", "stdout")

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

        value = self._lookup_field(source_node, edge.source_field, context)

        if edge.transformer_name:
            value = self._apply_transformer(edge.transformer_name, value, edge)

        # Auto-coerce JSON strings to native Python objects.
        # DAG mode: upstream stdout is often a JSON string that the downstream
        # skill expects as list/dict (e.g. fs.write expects writes: List[...]).
        value = self._try_json_coerce(value)

        return value

    @staticmethod
    def _try_json_coerce(value: Any) -> Any:
        """Attempt to deserialize a JSON string to a Python object.

        Only acts on str values that look like JSON arrays or objects.
        Returns the original value unchanged on any failure or non-string input.
        """
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if not stripped:
            return value
        # Only attempt for values that look like JSON containers
        if stripped[0] not in ('[', '{'):
            return value
        try:
            parsed = _json.loads(stripped)
            if isinstance(parsed, (list, dict)):
                logger.debug(
                    "[ParameterResolver] Auto-coerced JSON string (%d chars) → %s",
                    len(stripped), type(parsed).__name__,
                )
                return parsed
            return value
        except (_json.JSONDecodeError, ValueError):
            return value

    def _lookup_field(
        self,
        source_node: 'StepNode',
        source_field: str,
        context: Optional['ExecutionContext'] = None,
    ) -> Any:
        """
        Look up *source_field* in the source node's outputs.

        If the exact field is missing, try the standard fallback chain
        (output → result → content → stdout) so that AutoEdges created
        before the source node ran can still resolve correctly.
        """
        # Build the unified outputs dict (context takes precedence)
        outputs: Dict[str, Any] = {}
        if context:
            ctx_outputs = context.get_node_output(source_node.id)
            if ctx_outputs:
                outputs.update(ctx_outputs)
        if not outputs:
            outputs = source_node.outputs

        # Fast path: exact match
        if source_field in outputs:
            return outputs[source_field]

        # Fallback: walk priority chain
        for candidate in self._PRIMARY_OUTPUT_FALLBACKS:
            if candidate != source_field and candidate in outputs:
                logger.warning(
                    f"[EdgeResolve] '{source_field}' not in '{source_node.id}' outputs, "
                    f"falling back to '{candidate}'"
                )
                return outputs[candidate]

        raise ParameterResolutionError(
            f"Field '{source_field}' not found in '{source_node.id}' outputs. "
            f"Available: {list(outputs.keys())}"
        )

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
