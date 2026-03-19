from __future__ import annotations

"""MonitorContext — standardized monitoring context for SelfMonitor sub-detectors."""

from dataclasses import dataclass, field
from typing import Any, Optional

from .signals import SliceResult


@dataclass
class MonitorContext:
    """Standardized input for SelfMonitor sub-detectors."""

    task_id: str
    tick_count: int
    completed_items_count: int
    completed_items_delta: int
    current_blockers: list[str] = field(default_factory=list)
    recent_patches: list[dict[str, Any]] = field(default_factory=list)
    budget_utilization: dict[str, float] = field(default_factory=dict)
    working_memory_size_bytes: int = 0
    working_memory_size_limit: int = 0
    slice_result: Optional[SliceResult] = None
    unknown_ratio: float = 0.0
    recent_success_rate: float = 1.0
    consecutive_failures: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "tick_count": self.tick_count,
            "completed_items_count": self.completed_items_count,
            "completed_items_delta": self.completed_items_delta,
            "current_blockers": list(self.current_blockers),
            "recent_patches": [dict(p) for p in self.recent_patches],
            "budget_utilization": dict(self.budget_utilization),
            "working_memory_size_bytes": self.working_memory_size_bytes,
            "working_memory_size_limit": self.working_memory_size_limit,
            "slice_result": self.slice_result.to_dict() if self.slice_result else None,
            "unknown_ratio": self.unknown_ratio,
            "recent_success_rate": self.recent_success_rate,
            "consecutive_failures": self.consecutive_failures,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MonitorContext:
        sr_data = data.get("slice_result")
        return cls(
            task_id=data["task_id"],
            tick_count=data["tick_count"],
            completed_items_count=data["completed_items_count"],
            completed_items_delta=data["completed_items_delta"],
            current_blockers=list(data.get("current_blockers") or []),
            recent_patches=[dict(p) for p in (data.get("recent_patches") or [])],
            budget_utilization=dict(data.get("budget_utilization") or {}),
            working_memory_size_bytes=data.get("working_memory_size_bytes", 0),
            working_memory_size_limit=data.get("working_memory_size_limit", 0),
            slice_result=SliceResult.from_dict(sr_data) if sr_data else None,
            unknown_ratio=data.get("unknown_ratio", 0.0),
            recent_success_rate=data.get("recent_success_rate", 1.0),
            consecutive_failures=data.get("consecutive_failures", 0),
        )
