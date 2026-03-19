"""
Event emission and narrative helper mixin for GraphController.

Handles emitting plan.generated events and providing narrative context
summaries for nodes.

Extracted from graph_controller.py to keep the controller focused on
orchestration logic.
"""

from __future__ import annotations
from typing import Dict, Any, Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph

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
