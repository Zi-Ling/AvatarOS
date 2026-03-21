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
                from ..events.types import AgentEvent
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
    # 查询
    # ------------------------------------------------------------------

    def get_events(self) -> list[Dict[str, Any]]:
        """获取所有已记录事件."""
        return list(self._events)
