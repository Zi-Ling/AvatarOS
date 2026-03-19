from __future__ import annotations

"""TaskStateMachine — enforces legal state transitions for tasks."""

import time
from enum import Enum
from typing import Optional


class TaskState(str, Enum):
    CREATED = "created"
    QUEUED = "queued"
    EXECUTING = "executing"
    WAITING_INPUT = "waiting_input"
    BLOCKED = "blocked"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_VALID_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.CREATED:       {TaskState.QUEUED, TaskState.CANCELLED},
    TaskState.QUEUED:        {TaskState.EXECUTING, TaskState.CANCELLED},
    TaskState.EXECUTING:     {
        TaskState.WAITING_INPUT,
        TaskState.BLOCKED,
        TaskState.SUSPENDED,
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.CANCELLED,
    },
    TaskState.WAITING_INPUT: {TaskState.EXECUTING, TaskState.CANCELLED},
    TaskState.BLOCKED:       {TaskState.EXECUTING, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.SUSPENDED:     {TaskState.QUEUED, TaskState.CANCELLED},
    TaskState.COMPLETED:     set(),
    TaskState.FAILED:        set(),
    TaskState.CANCELLED:     set(),
}


class IllegalStateTransition(Exception):
    """Raised when a state transition is not allowed."""

    def __init__(self, from_state: TaskState, to_state: TaskState, reason: str = "") -> None:
        self.from_state = from_state
        self.to_state = to_state
        msg = f"Illegal transition: {from_state.value} -> {to_state.value}"
        if reason:
            msg += f" ({reason})"
        super().__init__(msg)


class TaskStateMachine:
    """Unified task state machine. All state transitions must go through this class."""

    def __init__(self, task_id: str, initial_state: TaskState = TaskState.CREATED) -> None:
        self._task_id = task_id
        self._state = initial_state
        self._history: list[tuple[TaskState, TaskState, str, float]] = []

    @property
    def task_id(self) -> str:
        return self._task_id

    @property
    def state(self) -> TaskState:
        return self._state

    def transition(self, target: TaskState, reason: str = "") -> None:
        """Execute a state transition. Raises IllegalStateTransition if not allowed."""
        valid = _VALID_TRANSITIONS.get(self._state, set())
        if target not in valid:
            raise IllegalStateTransition(self._state, target, reason)
        from_state = self._state
        self._state = target
        self._history.append((from_state, target, reason, time.time()))

    def get_history(self) -> list[tuple[TaskState, TaskState, str, float]]:
        """Return (from_state, to_state, reason, timestamp) transition history."""
        return list(self._history)
