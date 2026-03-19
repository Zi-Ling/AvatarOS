from __future__ import annotations

"""RuntimeSignal, RuntimeDecision, SliceResult, SignalType — core signal data models."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class SignalType(str, Enum):
    SWITCH_TASK = "switch_task"
    SUSPEND_TASK = "suspend_task"
    REQUIRE_APPROVAL = "require_approval"
    REQUEST_CLARIFICATION = "request_clarification"
    CREATE_FOLLOWUP_TASK = "create_followup_task"
    EMIT_STATUS_UPDATE = "emit_status_update"
    FALLBACK_SUBSYSTEM = "fallback_subsystem"
    BUDGET_WARNING = "budget_warning"
    SHRINK_BUDGET = "shrink_budget"
    STUCK_ALERT = "stuck_alert"
    LOOP_ALERT = "loop_alert"
    ENVIRONMENT_CHANGE = "environment_change"
    ESCALATE = "escalate"


@dataclass
class RuntimeSignal:
    signal_type: SignalType
    source_subsystem: str
    target_task_id: Optional[str] = None
    priority: int = 0
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_type": self.signal_type.value,
            "source_subsystem": self.source_subsystem,
            "target_task_id": self.target_task_id,
            "priority": self.priority,
            "reason": self.reason,
            "metadata": dict(self.metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeSignal:
        return cls(
            signal_type=SignalType(data["signal_type"]),
            source_subsystem=data["source_subsystem"],
            target_task_id=data.get("target_task_id"),
            priority=data.get("priority", 0),
            reason=data.get("reason", ""),
            metadata=dict(data.get("metadata") or {}),
            schema_version=data.get("schema_version", "1.0.0"),
        )


@dataclass
class RuntimeDecision:
    decision_type: str
    target_task_id: Optional[str] = None
    reason: str = ""
    contributing_signals: list[RuntimeSignal] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_type": self.decision_type,
            "target_task_id": self.target_task_id,
            "reason": self.reason,
            "contributing_signals": [s.to_dict() for s in self.contributing_signals],
            "metadata": dict(self.metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeDecision:
        return cls(
            decision_type=data["decision_type"],
            target_task_id=data.get("target_task_id"),
            reason=data.get("reason", ""),
            contributing_signals=[
                RuntimeSignal.from_dict(s) for s in data.get("contributing_signals", [])
            ],
            metadata=dict(data.get("metadata") or {}),
            schema_version=data.get("schema_version", "1.0.0"),
        )


@dataclass
class SliceResult:
    """GraphController bounded execution slice result."""
    terminal: bool
    checkpoint_id: Optional[str] = None
    execution_result: Optional[Any] = None
    signals: list[RuntimeSignal] = field(default_factory=list)
    elapsed_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "terminal": self.terminal,
            "checkpoint_id": self.checkpoint_id,
            "execution_result": self.execution_result,
            "signals": [s.to_dict() for s in self.signals],
            "elapsed_s": self.elapsed_s,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SliceResult:
        return cls(
            terminal=data["terminal"],
            checkpoint_id=data.get("checkpoint_id"),
            execution_result=data.get("execution_result"),
            signals=[
                RuntimeSignal.from_dict(s) for s in data.get("signals", [])
            ],
            elapsed_s=data.get("elapsed_s", 0.0),
        )
