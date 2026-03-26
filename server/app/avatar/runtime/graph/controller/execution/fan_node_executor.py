"""
FanOut/FanIn node execution mixin for GraphController.

Handles executing FanOut nodes (parallel sub-task splitting with concurrency
control) and FanIn nodes (result aggregation from upstream nodes).

Extracted from graph_controller.py to keep the controller focused on
orchestration logic.
"""

from __future__ import annotations
from typing import Any, Dict, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.graph.models.step_node import StepNode

logger = logging.getLogger(__name__)


class FanNodeExecutorMixin:
    """Mixin providing FanOut/FanIn execution methods for GraphController."""

    _MAX_FAN_OUT_CONCURRENCY = 5

    async def _execute_fan_out_node(
        self,
        fan_out_node: 'StepNode',
        graph: 'ExecutionGraph',
        shared_context: Any,
    ) -> None:
        """Execute a FanOutNode: split into parallel sub-tasks with concurrency control."""
        import asyncio
        from app.avatar.runtime.graph.models.step_node import NodeStatus

        try:
            child_nodes = []
            for edge in graph.edges.values():
                if edge.source_node == fan_out_node.id:
                    target = graph.nodes.get(edge.target_node)
                    if target and target.status == NodeStatus.PENDING:
                        child_nodes.append(target)

            if not child_nodes:
                fan_out_node.status = NodeStatus.SUCCESS
                fan_out_node.outputs = {"item_count": 0}
                return

            semaphore = asyncio.Semaphore(self._MAX_FAN_OUT_CONCURRENCY)
            fail_policy = getattr(fan_out_node, "batch_fail_policy", None)
            is_fail_fast = fail_policy and fail_policy.value == "fail_fast"

            results = {}
            cancel_event = asyncio.Event() if is_fail_fast else None

            async def _run_child(node: 'StepNode') -> None:
                if cancel_event and cancel_event.is_set():
                    node.status = NodeStatus.SKIPPED
                    return
                async with semaphore:
                    if cancel_event and cancel_event.is_set():
                        node.status = NodeStatus.SKIPPED
                        return
                    try:
                        await self.runtime.execute_ready_nodes(graph, context=shared_context)
                        results[node.id] = node.status
                    except Exception as _e:
                        node.status = NodeStatus.FAILED
                        node.error_message = str(_e)
                        results[node.id] = NodeStatus.FAILED
                        if cancel_event:
                            cancel_event.set()

            tasks = [asyncio.create_task(_run_child(cn)) for cn in child_nodes]
            await asyncio.gather(*tasks, return_exceptions=True)

            fan_out_node.status = NodeStatus.SUCCESS
            fan_out_node.outputs = {
                "item_count": len(child_nodes),
                "succeeded": sum(1 for s in results.values() if s == NodeStatus.SUCCESS),
                "failed": sum(1 for s in results.values() if s == NodeStatus.FAILED),
            }
        except Exception as _fo_err:
            logger.warning(f"[FanOut] Execution failed: {_fo_err}")
            fan_out_node.status = NodeStatus.FAILED
            fan_out_node.error_message = str(_fo_err)

    def _execute_fan_in_node(
        self,
        fan_in_node: 'StepNode',
        graph: 'ExecutionGraph',
    ) -> None:
        """Execute a FanInNode: aggregate results from upstream nodes."""
        from app.avatar.runtime.graph.models.step_node import NodeStatus

        try:
            upstream_results = []
            failed_items = []
            for edge in graph.edges.values():
                if edge.target_node == fan_in_node.id:
                    source = graph.nodes.get(edge.source_node)
                    if source is None:
                        continue
                    if source.status == NodeStatus.SUCCESS:
                        upstream_results.append(source.outputs or {})
                    elif source.status == NodeStatus.FAILED:
                        failed_items.append({
                            "node_id": source.id,
                            "error": source.error_message or "unknown",
                            "__failed__": True,
                        })

            agg_type = getattr(fan_in_node, "aggregation_type", None)
            agg_value = agg_type.value if agg_type else "concat"

            if agg_value == "merge":
                merged = {}
                for r in upstream_results:
                    merged.update(r)
                for fi in failed_items:
                    merged[fi["node_id"]] = fi
                fan_in_node.outputs = merged
            else:
                combined = list(upstream_results) + failed_items
                fan_in_node.outputs = {"results": combined}

            fan_in_node.status = NodeStatus.SUCCESS
        except Exception as _fi_err:
            logger.warning(f"[FanIn] Aggregation failed: {_fi_err}")
            fan_in_node.status = NodeStatus.FAILED
            fan_in_node.error_message = str(_fi_err)
