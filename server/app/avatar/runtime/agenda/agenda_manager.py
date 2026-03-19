from __future__ import annotations

"""AgendaManager — read-only partition views derived from TaskStateMachine states."""

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ..kernel.task_state_machine import TaskState, TaskStateMachine


@dataclass
class AgendaState:
    """Serializable snapshot of agenda state."""

    active_task_id: Optional[str] = None
    task_states: dict[str, str] = field(default_factory=dict)
    last_updated: float = field(default_factory=time.time)
    schema_version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_task_id": self.active_task_id,
            "task_states": dict(self.task_states),
            "last_updated": self.last_updated,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgendaState:
        return cls(
            active_task_id=data.get("active_task_id"),
            task_states=dict(data.get("task_states") or {}),
            last_updated=data.get("last_updated", time.time()),
            schema_version=data.get("schema_version", "1.0.0"),
        )


class AgendaManager:
    """Read-only partition views over TaskStateMachine instances.

    All partition views are derived from the current state of each
    TaskStateMachine — no independent state storage.
    """

    def __init__(self, state_machines: dict[str, TaskStateMachine]) -> None:
        self._machines = state_machines

    @property
    def active(self) -> Optional[str]:
        """Return the single executing task_id, or None. V1: max 1."""
        for tid, m in self._machines.items():
            if m.state == TaskState.EXECUTING:
                return tid
        return None

    @property
    def waiting(self) -> list[str]:
        """Task IDs in WAITING_INPUT state."""
        return [tid for tid, m in self._machines.items() if m.state == TaskState.WAITING_INPUT]

    @property
    def blocked(self) -> list[str]:
        """Task IDs in BLOCKED state."""
        return [tid for tid, m in self._machines.items() if m.state == TaskState.BLOCKED]

    @property
    def suspended(self) -> list[str]:
        """Task IDs in SUSPENDED state."""
        return [tid for tid, m in self._machines.items() if m.state == TaskState.SUSPENDED]

    @property
    def completed(self) -> list[str]:
        """Task IDs in COMPLETED state."""
        return [tid for tid, m in self._machines.items() if m.state == TaskState.COMPLETED]

    def get_state(self, task_id: str) -> TaskState:
        """Return the current state of a task."""
        return self._machines[task_id].state

    def get_all_tasks(self) -> dict[str, TaskState]:
        """Return a dict of task_id -> current TaskState."""
        return {tid: m.state for tid, m in self._machines.items()}

    def get_agenda_state(self) -> AgendaState:
        """Build a serializable AgendaState snapshot."""
        return AgendaState(
            active_task_id=self.active,
            task_states={tid: m.state.value for tid, m in self._machines.items()},
            last_updated=time.time(),
        )
