"""TraceIntegration — 多 Agent Trace 事件集成辅助函数.

封装 Agent 生命周期、HandoffEnvelope、multi_agent 事件发射。
每条记录包含时间戳、事件类型、来源/目标 Agent 标识、关联任务标识。

Requirements: 15.1, 15.2, 15.3, 15.5, 25.4
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class TraceIntegration:
    """多 Agent Trace 事件集成."""

    def __init__(self, event_bus: Optional[Any] = None) -> None:
        self._event_bus = event_bus
        self._events: list[Dict[str, Any]] = []  # 内存事件日志

    def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        """发射事件到 event_bus 并记录到内存日志."""
        event = {
            "event_type": event_type,
            "timestamp": time.time(),
            **payload,
        }
        self._events.append(event)
        if self._event_bus is not None:
            try:
                from app.avatar.runtime.events.types import AgentEvent
                agent_event = AgentEvent(
                    event_type=event_type,
                    source=payload.get("source_instance_id", ""),
                    payload=payload,
                )
                if hasattr(self._event_bus, "emit"):
                    self._event_bus.emit(event_type, agent_event.to_dict())
                elif hasattr(self._event_bus, "publish"):
                    self._event_bus.publish(agent_event)
            except Exception as exc:
                logger.debug("[TraceIntegration] event bus emit error: %s", exc)

    # ------------------------------------------------------------------
    # Agent 生命周期事件
    # ------------------------------------------------------------------

    def agent_created(self, instance_id: str, role_name: str, task_id: str = "") -> None:
        self._emit("agent.created", {
            "source_instance_id": instance_id,
            "role_name": role_name,
            "task_id": task_id,
        })

    def agent_activated(self, instance_id: str, role_name: str, task_id: str) -> None:
        self._emit("agent.activated", {
            "source_instance_id": instance_id,
            "role_name": role_name,
            "task_id": task_id,
        })

    def agent_idle(self, instance_id: str, role_name: str) -> None:
        self._emit("agent.idle", {
            "source_instance_id": instance_id,
            "role_name": role_name,
        })

    def agent_terminated(self, instance_id: str, role_name: str) -> None:
        self._emit("agent.terminated", {
            "source_instance_id": instance_id,
            "role_name": role_name,
        })

    def agent_task_assigned(
        self, instance_id: str, role_name: str, task_id: str
    ) -> None:
        self._emit("agent.task_assigned", {
            "source_instance_id": instance_id,
            "role_name": role_name,
            "task_id": task_id,
        })

    def agent_task_completed(
        self, instance_id: str, role_name: str, task_id: str
    ) -> None:
        self._emit("agent.task_completed", {
            "source_instance_id": instance_id,
            "role_name": role_name,
            "task_id": task_id,
        })

    def agent_feedback(
        self,
        instance_id: str,
        role_name: str,
        task_id: str,
        action: str = "",
        confidence: float = 0.0,
        suggestion: str = "",
    ) -> None:
        """Log worker-initiated feedback on task quality."""
        self._emit("agent.feedback", {
            "source_instance_id": instance_id,
            "role_name": role_name,
            "task_id": task_id,
            "feedback_action": action,
            "feedback_confidence": confidence,
            "feedback_suggestion": suggestion,
        })

    # ------------------------------------------------------------------
    # HandoffEnvelope 事件
    # ------------------------------------------------------------------

    def handoff_created(
        self, envelope_id: str, source_role: str, target_role: str, task_id: str = ""
    ) -> None:
        self._emit("handoff.created", {
            "envelope_id": envelope_id,
            "source_role": source_role,
            "target_role": target_role,
            "task_id": task_id,
        })

    def handoff_received(self, envelope_id: str, target_instance_id: str) -> None:
        self._emit("handoff.received", {
            "envelope_id": envelope_id,
            "target_instance_id": target_instance_id,
        })

    def handoff_completed(self, envelope_id: str) -> None:
        self._emit("handoff.completed", {"envelope_id": envelope_id})

    def handoff_rejected(self, envelope_id: str, reason: str = "") -> None:
        self._emit("handoff.rejected", {
            "envelope_id": envelope_id,
            "reason": reason,
        })

    def agent_handoff(
        self, source_role: str, target_role: str, task_id: str
    ) -> None:
        """Convenience: log a handoff between roles during execution."""
        self._emit("handoff.delivered", {
            "source_role": source_role,
            "target_role": target_role,
            "task_id": task_id,
        })

    # ------------------------------------------------------------------
    # Multi-Agent 事件
    # ------------------------------------------------------------------

    def multi_agent_started(self, goal: str, mode: str = "multi_agent") -> None:
        self._emit("multi_agent.started", {"goal": goal, "mode": mode})

    def multi_agent_completed(self, goal: str, status: str = "success") -> None:
        self._emit("multi_agent.completed", {"goal": goal, "status": status})

    def multi_agent_mode_decision(self, mode: str, reasoning: str = "") -> None:
        self._emit("multi_agent.mode_decision", {
            "mode": mode,
            "reasoning": reasoning,
        })

    # ------------------------------------------------------------------
    # Multi-Agent Observability (P2) — decomposition, layers, failures
    # ------------------------------------------------------------------

    def decomposition_result(
        self,
        task_count: int,
        roles: list,
        parallel_layers: int,
        node_summaries: list,
    ) -> None:
        """Log the result of semantic task decomposition."""
        self._emit("multi_agent.decomposition", {
            "task_count": task_count,
            "roles": roles,
            "parallel_layers": parallel_layers,
            "node_summaries": node_summaries,
        })

    def layer_started(
        self, layer_idx: int, total_layers: int, node_ids: list,
    ) -> None:
        """Log the start of a parallel execution layer."""
        self._emit("multi_agent.layer_started", {
            "layer_idx": layer_idx,
            "total_layers": total_layers,
            "node_ids": node_ids,
        })

    def layer_completed(
        self,
        layer_idx: int,
        completed: list,
        failed: list,
        blocked: list,
    ) -> None:
        """Log the completion of a parallel execution layer."""
        self._emit("multi_agent.layer_completed", {
            "layer_idx": layer_idx,
            "completed": completed,
            "failed": failed,
            "blocked": blocked,
        })

    def failure_propagated(
        self, failed_node_id: str, blocked_node_ids: list,
    ) -> None:
        """Log failure propagation from a failed node to its downstream."""
        self._emit("multi_agent.failure_propagated", {
            "failed_node_id": failed_node_id,
            "blocked_node_ids": blocked_node_ids,
        })

    def validation_result(
        self, valid: bool, errors: list,
    ) -> None:
        """Log GraphValidator result."""
        self._emit("multi_agent.validation", {
            "valid": valid,
            "errors": errors,
        })

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_events(self) -> list[Dict[str, Any]]:
        """获取所有已记录事件."""
        return list(self._events)

    def get_multi_agent_events(self) -> list[Dict[str, Any]]:
        """Get only multi-agent specific events (decomposition, layers, handoffs)."""
        _ma_prefixes = ("multi_agent.", "handoff.", "agent.")
        return [
            e for e in self._events
            if any(e.get("event_type", "").startswith(p) for p in _ma_prefixes)
        ]

    def get_summary(
        self,
        health_monitor: Optional[Any] = None,
        worker_pool: Optional[Any] = None,
        repair_loop: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Get a structured summary of the multi-agent execution trace.

        Optionally includes P1 management panel data when components are provided.
        """
        events = self.get_multi_agent_events()
        decomp = [e for e in events if e.get("event_type") == "multi_agent.decomposition"]
        layers = [e for e in events if e.get("event_type") == "multi_agent.layer_completed"]
        handoffs = [e for e in events if e.get("event_type") == "handoff.delivered"]
        failures = [e for e in events if e.get("event_type") == "multi_agent.failure_propagated"]

        summary: Dict[str, Any] = {
            "total_events": len(events),
            "decomposition": decomp[0] if decomp else None,
            "layers_completed": len(layers),
            "handoffs_delivered": len(handoffs),
            "failures_propagated": len(failures),
            "validation": next(
                (e for e in events if e.get("event_type") == "multi_agent.validation"),
                None,
            ),
        }

        # P2: management panel status
        if health_monitor is not None and hasattr(health_monitor, "get_summary"):
            summary["active_workers"] = health_monitor.get_summary()
        if worker_pool is not None and hasattr(worker_pool, "get_summary"):
            summary["pool_status"] = worker_pool.get_summary()
        if repair_loop is not None and hasattr(repair_loop, "get_summary"):
            summary["repair_actions"] = repair_loop.get_summary()

        return summary
