"""
Event emission and narrative helper mixin for GraphController.

Unified event source: GraphController is the single source of truth for
step lifecycle events (step.start, step.end, step.failed). Events are
emitted in real-time during execution via EventBus → SocketBridge → frontend.

executor.py's _emit_plan_and_steps is no longer needed — all events originate here.
"""

from __future__ import annotations
from typing import Dict, Any, Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.graph.models.step_node import StepNode

logger = logging.getLogger(__name__)


class EventEmitterMixin:
    """Mixin providing event emission and narrative helper methods for GraphController."""

    def _emit_plan_generated(self, graph: 'ExecutionGraph', env_context: Dict[str, Any]) -> None:
        """Emit plan.generated event for frontend progress display."""
        if not self.runtime.event_bus:
            return
        try:
            from app.avatar.runtime.events.types import Event, EventType
            nodes = list(graph.nodes.values())
            steps = [
                {
                    "id": str(n.id),
                    "skill": n.capability_name,
                    "skill_name": n.capability_name,
                    "description": (n.metadata or {}).get("description") or n.capability_name.replace(".", " → "),
                    "status": "pending",
                    "order": i,
                    "params": n.params or {},
                    "depends_on": [],
                }
                for i, n in enumerate(nodes)
            ]
            event = Event(
                type=EventType.PLAN_GENERATED,
                source="graph_controller",
                payload={
                    "session_id": env_context.get("session_id", ""),
                    "plan": {"id": graph.id, "goal": graph.goal, "steps": steps},
                },
            )
            self.runtime.event_bus.publish(event)
        except Exception as e:
            logger.warning(f"[GraphController] Failed to emit plan.generated: {e}")

    # ── Real-time step lifecycle events ─────────────────────────────────

    def _emit_step_start(self, node: 'StepNode', env_context: Dict[str, Any]) -> None:
        """Emit step.start when a node begins execution. Called from the ReAct loop."""
        if not self.runtime.event_bus:
            return
        try:
            from app.avatar.runtime.events.types import Event, EventType
            event = Event(
                type=EventType.STEP_START,
                source="graph_controller",
                step_id=str(node.id),
                payload={
                    "session_id": env_context.get("session_id", ""),
                    "skill_name": node.capability_name,
                    "description": (node.metadata or {}).get("description") or node.capability_name,
                    "params": node.params or {},
                },
            )
            self.runtime.event_bus.publish(event)
        except Exception as e:
            logger.debug(f"[EventEmitter] step.start failed for {node.id}: {e}")

    def _emit_step_end(self, node: 'StepNode', env_context: Dict[str, Any]) -> None:
        """Emit step.end when a node completes successfully."""
        if not self.runtime.event_bus:
            return
        try:
            from app.avatar.runtime.events.types import Event, EventType
            outputs = node.outputs or {}
            b64_image = outputs.get("base64_image") if isinstance(outputs, dict) else None
            artifact_ids = outputs.get("__artifacts__", []) if isinstance(outputs, dict) else []

            event = Event(
                type=EventType.STEP_END,
                source="graph_controller",
                step_id=str(node.id),
                payload={
                    "session_id": env_context.get("session_id", ""),
                    "skill_name": node.capability_name,
                    "status": "completed",
                    "raw_output": {k: v for k, v in outputs.items() if k != "__artifacts__"} if isinstance(outputs, dict) else outputs,
                    "base64_image": b64_image,
                    "artifact_ids": artifact_ids,
                },
            )
            self.runtime.event_bus.publish(event)
        except Exception as e:
            logger.debug(f"[EventEmitter] step.end failed for {node.id}: {e}")

    def _emit_step_failed(self, node: 'StepNode', env_context: Dict[str, Any]) -> None:
        """Emit step.failed when a node fails."""
        if not self.runtime.event_bus:
            return
        try:
            from app.avatar.runtime.events.types import Event, EventType
            outputs = node.outputs or {}
            event = Event(
                type=EventType.STEP_FAILED,
                source="graph_controller",
                step_id=str(node.id),
                payload={
                    "session_id": env_context.get("session_id", ""),
                    "skill_name": node.capability_name,
                    "status": "failed",
                    "raw_output": outputs if isinstance(outputs, dict) else {},
                    "error": node.error_message,
                },
            )
            self.runtime.event_bus.publish(event)
        except Exception as e:
            logger.debug(f"[EventEmitter] step.failed for {node.id}: {e}")

    def _emit_task_completed(self, graph: 'ExecutionGraph', env_context: Dict[str, Any]) -> None:
        """Emit task.completed when the entire graph finishes."""
        if not self.runtime.event_bus:
            return
        try:
            from app.avatar.runtime.events.types import Event, EventType
            from app.avatar.runtime.graph.models.execution_graph import GraphStatus
            is_failed = graph.status == GraphStatus.FAILED
            event = Event(
                type=EventType.TASK_COMPLETED,
                source="graph_controller",
                payload={
                    "session_id": env_context.get("session_id", ""),
                    "task": {
                        "id": str(graph.id),
                        "status": "FAILED" if is_failed else "SUCCESS",
                    },
                    "step_count": len(graph.nodes),
                },
            )
            self.runtime.event_bus.publish(event)
        except Exception as e:
            logger.debug(f"[EventEmitter] task.completed failed: {e}")

    # ── Helpers ─────────────────────────────────────────────────────────


    def _emit_realtime_step_events(self, s: Any, env_context: Dict[str, Any]) -> None:
        """Emit step.start/step.end/step.failed for nodes processed this iteration.

        Called after execute_ready_nodes in the ReAct loop. Replaces the old
        post-hoc _emit_plan_and_steps in executor.py.
        """
        from app.avatar.runtime.graph.models.step_node import NodeStatus
        for node in s.graph.nodes.values():
            if node.id not in s.pending_node_ids:
                continue
            if node.status == NodeStatus.SUCCESS:
                self._emit_step_end(node, env_context)
            elif node.status == NodeStatus.FAILED:
                self._emit_step_failed(node, env_context)

    @staticmethod
    def _summarize_params(params: Optional[Dict[str, Any]]) -> Optional[str]:
        """Summarize node params into a short string for narrative context."""
        if not params:
            return None
        for key in ("file", "path", "filename", "file_path", "url", "query", "code_path", "target"):
            val = params.get(key)
            if val and isinstance(val, str):
                if "/" in val or "\\" in val:
                    return val.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
                return val[:60]
        for val in params.values():
            if isinstance(val, str) and val.strip():
                return val[:60]
        return None

    @staticmethod
    def _summarize_output(node: Any) -> Optional[str]:
        """Summarize node outputs into a short string for narrative context."""
        if not node.outputs:
            return None
        for key in ("result", "summary", "output", "content", "message"):
            val = node.outputs.get(key)
            if val and isinstance(val, str):
                return val[:80]
        for val in node.outputs.values():
            if isinstance(val, str) and val.strip():
                return val[:80]
        return None

    @staticmethod
    def _get_semantic_label(node: Any) -> Optional[str]:
        """Extract semantic_label from node metadata/output_contract."""
        if not node.metadata:
            return None
        oc = node.metadata.get("output_contract")
        if oc is not None:
            if isinstance(oc, dict):
                label = oc.get("semantic_label")
            else:
                label = getattr(oc, "semantic_label", None)
            if label:
                return str(label)
        desc = node.metadata.get("description")
        if desc and isinstance(desc, str):
            return desc
        return None
