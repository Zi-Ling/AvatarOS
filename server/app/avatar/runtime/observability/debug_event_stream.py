"""
DebugEventStream — fire-and-forget observability for core object lifecycle events.

All emit() calls are best-effort: failures are logged but never block the main
execution flow.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DebugEvent:
    """Single debug event recording a core object lifecycle transition."""
    event_type: str       # "created" / "updated" / "consumed"
    object_type: str      # "TaskDefinition" / "StepOutputSchema" / ...
    object_id: str
    timestamp: float = 0.0
    payload_summary: str = ""
    schema_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "timestamp": self.timestamp,
            "payload_summary": self.payload_summary,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DebugEvent":
        return cls(
            event_type=data.get("event_type", ""),
            object_type=data.get("object_type", ""),
            object_id=data.get("object_id", ""),
            timestamp=data.get("timestamp", 0.0),
            payload_summary=data.get("payload_summary", ""),
            schema_version=data.get("schema_version", "1.0.0"),
        )


class DebugEventStream:
    """
    Best-effort event stream for debug/observability.

    All emit() calls are fire-and-forget. Failures are logged at DEBUG level
    and never propagate to callers.

    Supported event types (Requirement 12.2):
    - Core object lifecycle: created / updated / consumed / migrated / fallback
    - Agent loop: agent_loop.tick / agent_loop.task_switch
    - Memory: memory.query / memory.write
    - Event bus: event_bus.received / event_bus.triggered
    - Scheduler: scheduler.priority_change / scheduler.task_switch
    - Collaboration: collaboration.interaction
    - Action plane: action_plane.execute
    - Monitor: monitor.alert / monitor.stuck / monitor.loop / monitor.budget
              / monitor.uncertainty / monitor.context_health
    - Policy: policy.evaluated
    - Outcome: outcome.verified
    """

    _CURRENT_SCHEMA_VERSION = "1.0.0"
    _COMPATIBLE_VERSIONS = {"1.0.0"}

    # ── Runtime event type constants (Requirement 12.2) ──
    # Agent loop events
    AGENT_LOOP_TICK = "agent_loop.tick"
    AGENT_LOOP_TASK_SWITCH = "agent_loop.task_switch"
    # Memory events
    MEMORY_QUERY = "memory.query"
    MEMORY_WRITE = "memory.write"
    # Event bus events
    EVENT_BUS_RECEIVED = "event_bus.received"
    EVENT_BUS_TRIGGERED = "event_bus.triggered"
    # Scheduler events
    SCHEDULER_PRIORITY_CHANGE = "scheduler.priority_change"
    SCHEDULER_TASK_SWITCH = "scheduler.task_switch"
    # Collaboration events
    COLLABORATION_INTERACTION = "collaboration.interaction"
    # Action plane events
    ACTION_PLANE_EXECUTE = "action_plane.execute"
    # Monitor events
    MONITOR_ALERT = "monitor.alert"
    MONITOR_STUCK = "monitor.stuck"
    MONITOR_LOOP = "monitor.loop"
    MONITOR_BUDGET = "monitor.budget"
    MONITOR_UNCERTAINTY = "monitor.uncertainty"
    MONITOR_CONTEXT_HEALTH = "monitor.context_health"
    # Policy events
    POLICY_EVALUATED = "policy.evaluated"
    # Outcome events
    OUTCOME_VERIFIED = "outcome.verified"

    def __init__(self, max_buffer_size: int = 1000) -> None:
        self._buffer: List[DebugEvent] = []
        self._max_buffer_size = max_buffer_size
        self._listeners: List[Any] = []

    def emit(
        self,
        event_type: str,
        object_type: str,
        object_id: str,
        payload_summary: str = "",
    ) -> None:
        """Fire-and-forget event emission. Never raises."""
        try:
            event = DebugEvent(
                event_type=event_type,
                object_type=object_type,
                object_id=object_id,
                timestamp=time.time(),
                payload_summary=payload_summary[:500],  # Truncate large summaries
            )
            # Buffer management
            if len(self._buffer) >= self._max_buffer_size:
                self._buffer.pop(0)
            self._buffer.append(event)

            # Notify listeners (best-effort)
            for listener in self._listeners:
                try:
                    listener(event)
                except Exception:
                    pass

            logger.debug(
                f"[DebugEvent] {event_type} {object_type}({object_id}): "
                f"{payload_summary[:100]}"
            )
        except Exception as _e:
            logger.debug(f"[DebugEventStream] emit failed (non-blocking): {_e}")

    def add_listener(self, listener: Any) -> None:
        """Register a listener callback(event: DebugEvent)."""
        self._listeners.append(listener)

    def get_events(
        self,
        object_type: Optional[str] = None,
        object_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[DebugEvent]:
        """Query buffered events with optional filters."""
        filtered = self._buffer
        if object_type:
            filtered = [e for e in filtered if e.object_type == object_type]
        if object_id:
            filtered = [e for e in filtered if e.object_id == object_id]
        return filtered[-limit:]

    def clear(self) -> None:
        """Clear the event buffer."""
        self._buffer.clear()

    @classmethod
    def check_schema_version(cls, version: str) -> bool:
        """Check if a schema version is compatible with current version."""
        return version in cls._COMPATIBLE_VERSIONS

    @classmethod
    def migrate_event(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Attempt backward-compatible migration of a serialized event.

        Returns migrated data or original data if migration not needed/possible.
        """
        version = data.get("schema_version", "1.0.0")
        if version in cls._COMPATIBLE_VERSIONS:
            return data
        # Future: add migration logic for newer versions
        logger.warning(
            f"[DebugEventStream] Unknown schema_version={version}, "
            f"attempting best-effort load"
        )
        data["schema_version"] = cls._CURRENT_SCHEMA_VERSION
        return data


# ── Singleton instance ──────────────────────────────────────────────────

_global_stream: Optional[DebugEventStream] = None


def get_debug_event_stream() -> DebugEventStream:
    """Get or create the global DebugEventStream singleton."""
    global _global_stream
    if _global_stream is None:
        _global_stream = DebugEventStream()
    return _global_stream


# ── Schema version migration utility ────────────────────────────────────

_CURRENT_SCHEMA_VERSION = "1.0.0"
_COMPATIBLE_VERSIONS = {"1.0.0"}


def migrate_schema(data: Dict[str, Any], object_type: str = "") -> Dict[str, Any]:
    """
    Generic schema migration for any serialized core object.

    1. Check schema_version compatibility
    2. If compatible → return as-is
    3. If incompatible but migratable → attempt migration
    4. If not migratable → log warning, return with current version (best-effort)
    """
    version = data.get("schema_version", "1.0.0")
    if version in _COMPATIBLE_VERSIONS:
        return data

    logger.warning(
        f"[SchemaMigration] {object_type} has schema_version={version}, "
        f"current={_CURRENT_SCHEMA_VERSION}. Attempting best-effort migration."
    )

    # Future: add version-specific migration functions here
    # For now, stamp with current version and hope for the best
    data["schema_version"] = _CURRENT_SCHEMA_VERSION

    try:
        stream = get_debug_event_stream()
        stream.emit(
            "migrated", "SchemaMigration",
            f"migration_{object_type}_{int(time.time())}",
            f"from={version} to={_CURRENT_SCHEMA_VERSION}",
        )
    except Exception:
        pass

    return data


# ── Unified fallback helper (19.4) ─────────────────────────────────────

def record_system_fallback(
    subsystem: str,
    reason: str,
    strategy: str,
    task_runtime_state: Optional[Any] = None,
) -> None:
    """
    Unified helper for recording subsystem fallback events.

    Writes to:
    1. TaskRuntimeState.decision_log (update_source=system_fallback)
    2. DebugEventStream.emit()
    3. logger.warning()

    All operations are best-effort.
    """
    # 1. Logger
    logger.warning(f"[Fallback] {subsystem}: {reason} → {strategy}")

    # 2. DebugEventStream
    try:
        stream = get_debug_event_stream()
        stream.emit(
            event_type="fallback",
            object_type=subsystem,
            object_id=f"fallback_{subsystem}_{int(time.time())}",
            payload_summary=f"reason={reason}, strategy={strategy}",
        )
    except Exception:
        pass

    # 3. TaskRuntimeState
    if task_runtime_state is not None:
        try:
            from app.avatar.runtime.task.runtime_state import UpdateSource
            task_runtime_state.add_decision_log(
                decision_id=f"fallback_{subsystem}_{int(time.time())}",
                context=f"{subsystem} fallback triggered",
                decision=strategy,
                rationale=reason,
                update_source=UpdateSource.SYSTEM_FALLBACK,
            )
        except Exception:
            pass
