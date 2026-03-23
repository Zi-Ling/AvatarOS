from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional
import time


class EventType(str, Enum):
    # System
    SYSTEM_START = "system.start"
    SYSTEM_ERROR = "system.error"
    
    # Plan
    PLAN_GENERATED = "plan.generated"
    PLAN_UPDATED = "plan.updated"
    PLAN_REPLANNING = "plan.replanning"
    
    # Task (Task Level Updates)
    TASK_UPDATED = "task.updated"
    TASK_COMPLETED = "task.completed"
    
    # === NEW: Execution Flow Events ===
    # 思考阶段
    TASK_THINKING = "task.thinking"
    TASK_DECOMPOSED = "task.decomposed"
    
    # 执行流
    SUBTASK_START = "subtask.start"
    SUBTASK_PROGRESS = "subtask.progress"
    SUBTASK_COMPLETE = "subtask.complete"
    SUBTASK_FAILED = "subtask.failed"
    
    # Step
    STEP_START = "step.start"
    STEP_END = "step.end"
    STEP_SKIPPED = "step.skipped"
    STEP_FAILED = "step.failed"
    
    # LLM
    LLM_START = "llm.start"
    LLM_TOKEN = "llm.token"
    LLM_END = "llm.end"
    
    # Skill
    SKILL_START = "skill.start"
    SKILL_PROGRESS = "skill.progress"
    SKILL_END = "skill.end"
    
    # Filesystem
    FILE_CREATED = "file.created"
    FILE_MODIFIED = "file.modified"
    FILE_DELETED = "file.deleted"
    DIR_CREATED = "dir.created"
    DIR_DELETED = "dir.deleted"

    # Graph execution
    GRAPH_STARTED = "graph_started"
    GRAPH_COMPLETED = "graph_completed"
    GRAPH_FAILED = "graph_failed"
    NODE_STARTED = "node_started"
    NODE_COMPLETED = "node_completed"
    NODE_FAILED = "node_failed"

    # Multi-Agent events
    AGENT_CREATED = "agent.created"
    AGENT_ACTIVATED = "agent.activated"
    AGENT_IDLE = "agent.idle"
    AGENT_TERMINATED = "agent.terminated"
    AGENT_TASK_ASSIGNED = "agent.task_assigned"
    AGENT_TASK_COMPLETED = "agent.task_completed"

    HANDOFF_CREATED = "handoff.created"
    HANDOFF_RECEIVED = "handoff.received"
    HANDOFF_COMPLETED = "handoff.completed"
    HANDOFF_REJECTED = "handoff.rejected"

    MULTI_AGENT_STARTED = "multi_agent.started"
    MULTI_AGENT_COMPLETED = "multi_agent.completed"
    MULTI_AGENT_MODE_DECISION = "multi_agent.mode_decision"

    # Workflow orchestration events
    WORKFLOW_INSTANCE_COMPLETED = "workflow.instance.completed"

    # Computer Use events
    COMPUTER_OBSERVE_STARTED = "computer.observe.started"
    COMPUTER_OBSERVE_COMPLETED = "computer.observe.completed"
    COMPUTER_ANALYZE_COMPLETED = "computer.analyze.completed"
    COMPUTER_LOCATE_COMPLETED = "computer.locate.completed"
    COMPUTER_THINK_COMPLETED = "computer.think.completed"
    COMPUTER_ACT_STARTED = "computer.act.started"
    COMPUTER_ACT_COMPLETED = "computer.act.completed"
    COMPUTER_VERIFY_COMPLETED = "computer.verify.completed"
    COMPUTER_RETRY_SCHEDULED = "computer.retry.scheduled"
    COMPUTER_STUCK_DETECTED = "computer.stuck.detected"
    COMPUTER_APPROVAL_REQUESTED = "computer.approval.requested"
    COMPUTER_INTERRUPTED = "computer.interrupted"
    COMPUTER_FINISHED = "computer.finished"
    COMPUTER_PROGRESS = "computer.progress"


@dataclass
class Event:
    type: EventType
    source: str  # "planner", "runner", "llm", "skill"
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    
    # Optional correlation IDs
    run_id: Optional[str] = None
    step_id: Optional[str] = None

# ---------------------------------------------------------------------------
# V2 extensions: AgentEvent, EventSource protocol, TriggerRule, EventSource adapters
# Requirements: 4.2, 4.3, 4.5
# ---------------------------------------------------------------------------

import uuid
from typing import Protocol, runtime_checkable


@dataclass
class AgentEvent:
    """Standardised agent-level event.

    Requirements: 4.2
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = ""
    source: str = ""
    timestamp: float = field(default_factory=time.time)
    payload: Dict[str, Any] = field(default_factory=dict)
    priority: str = "medium"  # low / medium / high / critical
    schema_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "source": self.source,
            "timestamp": self.timestamp,
            "payload": dict(self.payload),
            "priority": self.priority,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentEvent":
        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            event_type=data.get("event_type", ""),
            source=data.get("source", ""),
            timestamp=data.get("timestamp", time.time()),
            payload=dict(data.get("payload") or {}),
            priority=data.get("priority", "medium"),
            schema_version=data.get("schema_version", "1.0.0"),
        )


@runtime_checkable
class EventSource(Protocol):
    """EventSource adapter protocol.

    Requirements: 4.3
    """

    @property
    def source_id(self) -> str: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    @property
    def is_healthy(self) -> bool: ...


@dataclass
class TriggerRule:
    """Condition-action event response rule.

    Requirements: 4.5
    """

    rule_id: str = ""
    event_pattern: str = ""  # event_type exact match
    payload_conditions: Dict[str, Any] = field(default_factory=dict)
    condition: Optional[str] = None
    action: str = ""  # create_task / update_priority / notify_user / emit_signal
    action_params: Dict[str, Any] = field(default_factory=dict)
    cooldown: float = 60.0
    priority: int = 0
    enabled: bool = True
    schema_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "event_pattern": self.event_pattern,
            "payload_conditions": dict(self.payload_conditions),
            "condition": self.condition,
            "action": self.action,
            "action_params": dict(self.action_params),
            "cooldown": self.cooldown,
            "priority": self.priority,
            "enabled": self.enabled,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TriggerRule":
        return cls(
            rule_id=data.get("rule_id", ""),
            event_pattern=data.get("event_pattern", ""),
            payload_conditions=dict(data.get("payload_conditions") or {}),
            condition=data.get("condition"),
            action=data.get("action", ""),
            action_params=dict(data.get("action_params") or {}),
            cooldown=data.get("cooldown", 60.0),
            priority=data.get("priority", 0),
            enabled=data.get("enabled", True),
            schema_version=data.get("schema_version", "1.0.0"),
        )


# ---------------------------------------------------------------------------
# V1 EventSource adapters
# Requirements: 4.3
# ---------------------------------------------------------------------------


class FileWatcher:
    """V1 file-system change watcher EventSource adapter."""

    def __init__(self, source_id: str = "file_watcher", watch_path: str = ".") -> None:
        self._source_id = source_id
        self._watch_path = watch_path
        self._healthy = False

    @property
    def source_id(self) -> str:
        return self._source_id

    async def start(self) -> None:
        self._healthy = True

    async def stop(self) -> None:
        self._healthy = False

    @property
    def is_healthy(self) -> bool:
        return self._healthy


class WebhookReceiver:
    """V1 external webhook receiver EventSource adapter."""

    def __init__(self, source_id: str = "webhook_receiver", endpoint: str = "/webhook") -> None:
        self._source_id = source_id
        self._endpoint = endpoint
        self._healthy = False

    @property
    def source_id(self) -> str:
        return self._source_id

    async def start(self) -> None:
        self._healthy = True

    async def stop(self) -> None:
        self._healthy = False

    @property
    def is_healthy(self) -> bool:
        return self._healthy


class InternalMonitor:
    """V1 internal state monitor EventSource adapter.

    Monitors: task timeout, resource exhaustion, subsystem anomalies.
    """

    def __init__(self, source_id: str = "internal_monitor") -> None:
        self._source_id = source_id
        self._healthy = False

    @property
    def source_id(self) -> str:
        return self._source_id

    async def start(self) -> None:
        self._healthy = True

    async def stop(self) -> None:
        self._healthy = False

    @property
    def is_healthy(self) -> bool:
        return self._healthy
