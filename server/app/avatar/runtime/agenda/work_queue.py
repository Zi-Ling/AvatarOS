from __future__ import annotations

"""WorkQueue — priority-sorted task entry pool for the Agent runtime."""

import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class WorkQueueEntry:
    """A single entry in the WorkQueue."""

    task_id: str
    priority_score: float
    deadline: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    context_snapshot_id: Optional[str] = None
    dependencies: list[str] = field(default_factory=list)
    resource_budget: dict[str, float] = field(default_factory=dict)
    schema_version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "priority_score": self.priority_score,
            "deadline": self.deadline,
            "created_at": self.created_at,
            "context_snapshot_id": self.context_snapshot_id,
            "dependencies": list(self.dependencies),
            "resource_budget": dict(self.resource_budget),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkQueueEntry:
        return cls(
            task_id=data["task_id"],
            priority_score=data["priority_score"],
            deadline=data.get("deadline"),
            created_at=data.get("created_at", time.time()),
            context_snapshot_id=data.get("context_snapshot_id"),
            dependencies=list(data.get("dependencies") or []),
            resource_budget=dict(data.get("resource_budget") or {}),
            schema_version=data.get("schema_version", "1.0.0"),
        )


class WorkQueue:
    """Priority-sorted task entry pool. Does NOT maintain task state."""

    def __init__(self) -> None:
        self._entries: dict[str, WorkQueueEntry] = {}

    def push(self, entry: WorkQueueEntry) -> None:
        """Add or replace an entry in the queue."""
        self._entries[entry.task_id] = entry

    def pop(self) -> Optional[WorkQueueEntry]:
        """Remove and return the highest-priority entry, or None."""
        if not self._entries:
            return None
        best_id = max(self._entries, key=lambda tid: self._entries[tid].priority_score)
        return self._entries.pop(best_id)

    def peek(self) -> Optional[WorkQueueEntry]:
        """Return the highest-priority entry without removing it, or None."""
        if not self._entries:
            return None
        best_id = max(self._entries, key=lambda tid: self._entries[tid].priority_score)
        return self._entries[best_id]

    def remove(self, task_id: str) -> bool:
        """Remove an entry by task_id. Returns True if found."""
        if task_id in self._entries:
            del self._entries[task_id]
            return True
        return False

    def update_priority(self, task_id: str, new_score: float) -> None:
        """Update the priority_score of an existing entry."""
        if task_id in self._entries:
            self._entries[task_id].priority_score = new_score

    def list_entries(self) -> list[WorkQueueEntry]:
        """Return all entries sorted by priority_score descending."""
        return sorted(self._entries.values(), key=lambda e: e.priority_score, reverse=True)
