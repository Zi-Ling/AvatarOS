from __future__ import annotations

"""RuntimeKernel — orchestration core + Decision Applier.

Provides lifecycle management, subsystem registration, signal merging,
and atomic decision execution for the Agent runtime.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from .signals import RuntimeDecision, RuntimeSignal, SignalType
from .task_state_machine import TaskState, TaskStateMachine
from .task_state_machine import TaskState, TaskStateMachine
logger = logging.getLogger(__name__)

# Priority tiers for signal conflict resolution (higher index = higher priority).
_SIGNAL_PRIORITY: dict[SignalType, int] = {
    SignalType.EMIT_STATUS_UPDATE:    0,
    SignalType.CREATE_FOLLOWUP_TASK:  1,
    SignalType.BUDGET_WARNING:        2,
    SignalType.SHRINK_BUDGET:         3,
    SignalType.SWITCH_TASK:           4,
    SignalType.SUSPEND_TASK:          5,
    SignalType.REQUIRE_APPROVAL:      5,
    SignalType.ESCALATE:              6,
}

_DEFAULT_PRIORITY = -1


@dataclass
class AgentLoopState:
    """Runtime-level loop state (not task-level)."""

    is_paused: bool = False
    is_running: bool = False
    tick_count: int = 0
    schema_version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_paused": self.is_paused,
            "is_running": self.is_running,
            "tick_count": self.tick_count,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentLoopState:
        return cls(
            is_paused=data.get("is_paused", False),
            is_running=data.get("is_running", False),
            tick_count=data.get("tick_count", 0),
            schema_version=data.get("schema_version", "1.0.0"),
        )


class RuntimeKernel:
    """Orchestration core: lifecycle + signal merge + atomic decision execution."""

    def __init__(self) -> None:
        self._subsystems: dict[str, Any] = {}
        self._fallbacks: dict[str, Any] = {}
        self._loop_state = AgentLoopState()
        self._state_machines: dict[str, TaskStateMachine] = {}
        self._snapshots: dict[str, bytes] = {}
        self._active_task_id: Optional[str] = None
        self._work_queue: Any = None
        self._agenda_manager: Any = None
        self._collaboration_hub: Any = None

    @property
    def loop_state(self) -> AgentLoopState:
        return self._loop_state

    @property
    def state_machines(self) -> dict[str, TaskStateMachine]:
        return self._state_machines

    @property
    def active_task_id(self) -> Optional[str]:
        return self._active_task_id

    @property
    def snapshots(self) -> dict[str, bytes]:
        return self._snapshots

    # ── lifecycle ──

    def start(self) -> None:
        self._loop_state.is_running = True
        self._loop_state.is_paused = False

    def pause(self) -> None:
        self._loop_state.is_paused = True

    def resume(self) -> None:
        self._loop_state.is_paused = False

    def shutdown(self, timeout_s: float = 30.0) -> None:
        for tid, machine in list(self._state_machines.items()):
            if machine.state == TaskState.EXECUTING:
                try:
                    self._snapshot_task(tid)
                    machine.transition(TaskState.SUSPENDED, reason="shutdown")
                except Exception:
                    pass
        self._loop_state.is_running = False
        self._loop_state.is_paused = False
        self._active_task_id = None

    # ── subsystem management ──

    def register_subsystem(self, name: str, subsystem: Any, fallback: Any = None) -> None:
        self._subsystems[name] = subsystem
        if fallback is not None:
            self._fallbacks[name] = fallback
        if name == "work_queue":
            self._work_queue = subsystem
        elif name == "agenda_manager":
            self._agenda_manager = subsystem
        elif name == "collaboration_hub":
            self._collaboration_hub = subsystem

    def get_subsystem(self, name: str) -> Any:
        from ..feature_flags import get_capability_registry
        registry = get_capability_registry()
        if registry.is_available(name):
            return self._subsystems.get(name)
        return self._fallbacks.get(name)

    # ── task management ──

    def register_task(self, task_id: str, initial_state: TaskState = TaskState.CREATED) -> TaskStateMachine:
        machine = TaskStateMachine(task_id, initial_state=initial_state)
        self._state_machines[task_id] = machine
        return machine

    def complete_task(self, task_id: str, reason: str = "completed") -> None:
        """Transition a task to COMPLETED and trigger distillation.

        Requirements: 2.8
        """
        machine = self._state_machines.get(task_id)
        if machine is None:
            return
        machine.transition(TaskState.COMPLETED, reason=reason)
        if self._active_task_id == task_id:
            self._active_task_id = None
        self.trigger_task_completion_distillation(task_id)

    # ── signal / decision ──

    @staticmethod
    def merge_signals(signals: list[RuntimeSignal]) -> RuntimeDecision:
        if not signals:
            return RuntimeDecision(
                decision_type=SignalType.EMIT_STATUS_UPDATE.value,
                reason="no signals",
                contributing_signals=[],
            )

        def _sort_key(sig: RuntimeSignal) -> tuple[int, int]:
            return (
                _SIGNAL_PRIORITY.get(sig.signal_type, _DEFAULT_PRIORITY),
                sig.priority,
            )

        winner = max(signals, key=_sort_key)
        return RuntimeDecision(
            decision_type=winner.signal_type.value,
            target_task_id=winner.target_task_id,
            reason=winner.reason,
            contributing_signals=list(signals),
            metadata=dict(winner.metadata),
        )

    def apply_decision(self, decision: RuntimeDecision) -> None:
        """Atomically execute a decision. Rolls back kernel state on failure."""
        dt = decision.decision_type
        prev_active = self._active_task_id
        prev_snapshots = dict(self._snapshots)
        prev_states: dict[str, TaskState] = {
            tid: m.state for tid, m in self._state_machines.items()
        }
        try:
            handler = self._DECISION_HANDLERS.get(dt)
            if handler is not None:
                handler(self, decision)
        except Exception:
            self._active_task_id = prev_active
            self._snapshots = prev_snapshots
            for tid, prev_st in prev_states.items():
                m = self._state_machines.get(tid)
                if m is not None and m.state != prev_st:
                    m._state = prev_st
            raise

    # ── decision handlers ──

    def _apply_switch_task(self, decision: RuntimeDecision) -> None:
        target_id = decision.target_task_id
        if target_id is None:
            return
        if self._active_task_id and self._active_task_id in self._state_machines:
            cur = self._state_machines[self._active_task_id]
            if cur.state == TaskState.EXECUTING:
                self._snapshot_task(self._active_task_id)
                cur.transition(TaskState.SUSPENDED, reason="switch_task")
        if target_id in self._state_machines:
            tgt = self._state_machines[target_id]
            if tgt.state == TaskState.SUSPENDED:
                tgt.transition(TaskState.QUEUED, reason="switch_requeue")
            if tgt.state == TaskState.QUEUED:
                tgt.transition(TaskState.EXECUTING, reason="switch_task")
            self._restore_task(target_id)
            self._active_task_id = target_id
            self._goal_review(target_id)

    def _apply_suspend_task(self, decision: RuntimeDecision) -> None:
        target_id = decision.target_task_id or self._active_task_id
        if not target_id or target_id not in self._state_machines:
            return
        machine = self._state_machines[target_id]
        target_state_str = decision.metadata.get("target_state", "suspended")
        self._snapshot_task(target_id)
        if target_state_str == "blocked" and machine.state == TaskState.EXECUTING:
            machine.transition(TaskState.BLOCKED, reason=decision.reason)
        elif machine.state == TaskState.EXECUTING:
            machine.transition(TaskState.SUSPENDED, reason=decision.reason)
        if self._active_task_id == target_id:
            self._active_task_id = None

    def _apply_create_followup(self, decision: RuntimeDecision) -> None:
        if self._work_queue is None:
            return
        from ..agenda.work_queue import WorkQueueEntry
        meta = decision.metadata
        entry = WorkQueueEntry(
            task_id=meta.get("task_id", f"followup_{time.time()}"),
            priority_score=meta.get("priority_score", 0.5),
            deadline=meta.get("deadline"),
            dependencies=meta.get("dependencies", []),
            resource_budget=meta.get("resource_budget", {}),
        )
        self._work_queue.push(entry)

    def _apply_emit_status(self, decision: RuntimeDecision) -> None:
        if self._collaboration_hub is not None:
            try:
                self._collaboration_hub.notify_status(decision)
            except Exception:
                pass

    def _apply_fallback_subsystem(self, decision: RuntimeDecision) -> None:
        name = decision.metadata.get("subsystem_name", "")
        if name and name in self._subsystems:
            fb = self._fallbacks.get(name)
            if fb is not None:
                self._subsystems[name] = fb

    def _apply_require_approval(self, decision: RuntimeDecision) -> None:
        target_id = decision.target_task_id or self._active_task_id
        if target_id and target_id in self._state_machines:
            machine = self._state_machines[target_id]
            if machine.state == TaskState.EXECUTING:
                machine.transition(TaskState.WAITING_INPUT, reason=decision.reason)
                if self._active_task_id == target_id:
                    self._active_task_id = None
        if self._collaboration_hub is not None:
            try:
                self._collaboration_hub.request_approval(decision)
            except Exception:
                pass

    def _apply_shrink_budget(self, decision: RuntimeDecision) -> None:
        bg = self._subsystems.get("budget_guard_v2")
        if bg is not None:
            try:
                bg.enter_shrink_mode()
            except Exception:
                pass

    def _apply_escalate(self, decision: RuntimeDecision) -> None:
        target_id = decision.target_task_id or self._active_task_id
        if target_id and target_id in self._state_machines:
            machine = self._state_machines[target_id]
            if machine.state == TaskState.EXECUTING:
                self._snapshot_task(target_id)
                machine.transition(TaskState.WAITING_INPUT, reason="escalated")
                if self._active_task_id == target_id:
                    self._active_task_id = None
        if self._collaboration_hub is not None:
            try:
                self._collaboration_hub.escalate(decision)
            except Exception:
                pass

    # Handler dispatch table
    _DECISION_HANDLERS: dict[str, Any] = {
        SignalType.SWITCH_TASK.value: _apply_switch_task,
        SignalType.SUSPEND_TASK.value: _apply_suspend_task,
        SignalType.CREATE_FOLLOWUP_TASK.value: _apply_create_followup,
        SignalType.EMIT_STATUS_UPDATE.value: _apply_emit_status,
        SignalType.FALLBACK_SUBSYSTEM.value: _apply_fallback_subsystem,
        SignalType.REQUIRE_APPROVAL.value: _apply_require_approval,
        SignalType.SHRINK_BUDGET.value: _apply_shrink_budget,
        SignalType.ESCALATE.value: _apply_escalate,
    }

    # ── snapshot management ──

    def _snapshot_task(self, task_id: str) -> None:
        self._snapshots[task_id] = f"snapshot:{task_id}:{time.time()}".encode()

    def _restore_task(self, task_id: str) -> None:
        if task_id in self._snapshots:
            logger.debug("[RuntimeKernel] restored snapshot for %s", task_id)

    def _goal_review(self, task_id: str) -> None:
        logger.debug("[RuntimeKernel] goal review for %s", task_id)

    # ── task completion distillation ──

    def trigger_task_completion_distillation(self, task_id: str) -> None:
        """Trigger auto-distillation of TaskRuntimeState → ProjectMemory.

        Called when a task transitions to COMPLETED.
        Extracts successful_patterns and failure_lessons.
        Requirements: 2.8
        """
        try:
            from ..negotiation.distillation import distill_to_project_memory

            memory_system = self._subsystems.get("memory_system")
            if memory_system is None:
                return

            project_memory = None
            if hasattr(memory_system, "get_project_memory"):
                project_memory = memory_system.get_project_memory()

            # Try to get TaskRuntimeState from working memory or subsystems
            task_runtime_state = None
            if hasattr(memory_system, "get_working_memory"):
                wm = memory_system.get_working_memory(task_id)
                task_runtime_state = getattr(wm, "_task_runtime_state", None)

            if task_runtime_state is None:
                # Try from subsystem registry
                task_runtime_state = self._subsystems.get(f"task_runtime_state:{task_id}")

            if project_memory is not None and task_runtime_state is not None:
                distill_to_project_memory(task_runtime_state, project_memory, task_id)
                logger.info("[RuntimeKernel] Distillation completed for task %s", task_id)
        except Exception as exc:
            logger.warning("[RuntimeKernel] Distillation failed for task %s: %s", task_id, exc)
