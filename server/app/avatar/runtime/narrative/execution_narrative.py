"""
ExecutionNarrative — real-time user-facing execution summary.

Translates internal execution state into human-readable narrative.
Pushed via WebSocket as ``server_event`` with type ``narrative.update``.

Backward-compatible: the legacy ``ExecutionNarrative`` dataclass and
``VERDICT_TRANSLATIONS`` dict are preserved for existing consumers.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.avatar.runtime.narrative.models import (
    NarrativeEvent,
    NarrativeEventPayload,
    TranslationContext,
)
from app.avatar.runtime.narrative.narrative_mapper import NarrativeMapper

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Verdict translation (kept for backward compatibility)
# ---------------------------------------------------------------------------

VERDICT_TRANSLATIONS: Dict[str, str] = {
    "PASS": "验证通过",
    "passed": "验证通过",
    "FAIL": "验证失败",
    "failed": "验证失败",
    "UNCERTAIN": "结果不确定，需人工确认",
    "uncertain": "结果不确定，需人工确认",
    "partial_success": "部分完成",
    "PARTIAL_SUCCESS": "部分完成",
    "completed": "已完成",
    "repair_exhausted": "修复次数已耗尽",
}


# ---------------------------------------------------------------------------
# ExecutionNarrative dataclass (kept for backward compatibility)
# ---------------------------------------------------------------------------

@dataclass
class ExecutionNarrative:
    """
    User-facing execution narrative (legacy dataclass).
    Kept for backward compatibility with existing consumers.
    """
    goal: str
    completed: List[str] = field(default_factory=list)
    remaining: List[str] = field(default_factory=list)
    verification_result: Optional[str] = None
    final_artifacts: List[Dict[str, Any]] = field(default_factory=list)
    repair_hint: Optional[str] = None
    session_id: Optional[str] = None
    task_id: Optional[str] = None


# ---------------------------------------------------------------------------
# NarrativeManager — lifecycle coordinator with event-driven architecture
# ---------------------------------------------------------------------------

class NarrativeManager:
    """
    Lifecycle coordinator: listens for events, calls Mapper, assigns
    sequence numbers, maintains a replay buffer, and pushes via WebSocket.

    Usage::

        mapper = NarrativeMapper()
        manager = NarrativeManager(session_id, task_id, goal, mapper, socket_manager)
        await manager.on_event("step.start", step_id="s1", context=TranslationContext(...))

    Legacy methods (``on_step_completed``, ``on_verdict``, ``on_repair_triggered``)
    are preserved and internally delegate to ``on_event()``.
    """

    BUFFER_MAX = 500
    MAX_PUSH_RETRIES = 3
    LONG_RUNNING_THRESHOLD_SECS = 5

    def __init__(
        self,
        session_id: str,
        task_id: str,
        goal: str,
        mapper: NarrativeMapper,
        socket_manager: Optional[Any] = None,
        event_bus: Optional[Any] = None,
        sub_goals: Optional[List[str]] = None,
    ) -> None:
        self._session_id = session_id
        self._task_id = task_id
        self._goal = goal
        self._mapper = mapper
        self._socket_manager = socket_manager
        self._event_bus = event_bus
        self._sequence: int = 0
        self._buffer: list[NarrativeEvent] = []
        self._long_running_timers: dict[str, asyncio.TimerHandle] = {}

        # Legacy narrative dataclass (kept for backward compat)
        self.narrative = ExecutionNarrative(
            goal=goal,
            remaining=list(sub_goals or []),
            session_id=session_id,
            task_id=task_id,
        )

    # ── Unified event entry point ─────────────────────────────────────

    async def on_event(
        self,
        internal_event_type: str,
        step_id: str,
        context: TranslationContext,
    ) -> NarrativeEvent:
        """
        Unified event entry point:
        1. Call mapper.translate() to get payload
        2. Assign monotonically increasing sequence
        3. Generate event_id (UUID)
        4. Store in buffer (trim if over limit)
        5. Push via WebSocket (failures don't discard the event)
        6. Manage long-running timers for step.start / step.end / step.failed
        """
        # 1. Translate
        payload: NarrativeEventPayload = self._mapper.translate(
            internal_event_type, step_id, context,
        )

        # 2. Assign sequence
        self._sequence += 1
        seq = self._sequence

        # 3. Generate event_id and timestamp
        event = NarrativeEvent(
            event_id=str(uuid.uuid4()),
            run_id=self._task_id,
            step_id=payload.step_id,
            event_type=payload.event_type,
            source_event_type=payload.source_event_type,
            level=payload.level,
            phase=payload.phase,
            status=payload.status,
            description=payload.description,
            timestamp=datetime.now(timezone.utc).isoformat(),
            sequence=seq,
            metadata=payload.metadata,
        )

        # 4. Store in buffer
        self._buffer.append(event)
        if len(self._buffer) > self.BUFFER_MAX:
            self._trim_buffer()

        # 5. Push via WebSocket
        await self._push(event)

        # 6. Manage long-running timers
        if internal_event_type == "step.start":
            self._start_long_running_timer(step_id, context)
        elif internal_event_type in ("step.end", "step.failed"):
            self._cancel_long_running_timer(step_id)

        return event

    # ── Replay support ────────────────────────────────────────────────

    async def replay_after(self, after_sequence: int) -> list[dict]:
        """Return buffered events with sequence > *after_sequence*."""
        return [
            e.to_dict()
            for e in self._buffer
            if e.sequence > after_sequence
        ]

    # ── Buffer trimming ───────────────────────────────────────────────

    def _trim_buffer(self) -> None:
        """Trim buffer to BUFFER_MAX, preferring to keep major events.

        Strategy: remove the earliest minor events first until we are
        at or below the limit.  If still over, remove the earliest
        events regardless of level.
        """
        if len(self._buffer) <= self.BUFFER_MAX:
            return

        excess = len(self._buffer) - self.BUFFER_MAX

        # Phase 1: remove earliest minor events
        minor_indices = [
            i for i, e in enumerate(self._buffer) if e.level == "minor"
        ]
        to_remove: set[int] = set()
        for idx in minor_indices:
            if len(to_remove) >= excess:
                break
            to_remove.add(idx)

        if len(to_remove) >= excess:
            self._buffer = [
                e for i, e in enumerate(self._buffer) if i not in to_remove
            ]
            return

        # Phase 2: still over — remove earliest events regardless of level
        remaining_excess = excess - len(to_remove)
        all_indices = [
            i for i in range(len(self._buffer)) if i not in to_remove
        ]
        for idx in all_indices[:remaining_excess]:
            to_remove.add(idx)

        self._buffer = [
            e for i, e in enumerate(self._buffer) if i not in to_remove
        ]

    # ── Long-running timer management ─────────────────────────────────

    def _start_long_running_timer(
        self, step_id: str, context: TranslationContext,
    ) -> None:
        """Start a timer that fires a ``tool.long_running`` minor event
        if the step hasn't completed within LONG_RUNNING_THRESHOLD_SECS."""
        self._cancel_long_running_timer(step_id)

        loop = asyncio.get_event_loop()
        handle = loop.call_later(
            self.LONG_RUNNING_THRESHOLD_SECS,
            lambda: asyncio.ensure_future(
                self._fire_long_running(step_id, context),
            ),
        )
        self._long_running_timers[step_id] = handle

    def _cancel_long_running_timer(self, step_id: str) -> None:
        """Cancel the long-running timer for *step_id* if it exists."""
        handle = self._long_running_timers.pop(step_id, None)
        if handle is not None:
            handle.cancel()

    async def _fire_long_running(
        self, step_id: str, context: TranslationContext,
    ) -> None:
        """Emit a ``tool.long_running`` minor event for a long-running step."""
        self._long_running_timers.pop(step_id, None)
        try:
            await self.on_event("tool.long_running", step_id, context)
        except Exception as exc:
            logger.debug(
                "[NarrativeManager] long-running event failed: %s", exc,
            )

    # ── WebSocket push ────────────────────────────────────────────────

    async def _push(self, event: NarrativeEvent) -> None:
        """Push a narrative event via EventBus or WebSocket.

        Priority: EventBus > SocketManager
        Retries up to MAX_PUSH_RETRIES times with exponential backoff
        (100ms / 200ms / 300ms).  On failure the event stays in the
        buffer for later replay.
        """
        # First try EventBus
        if self._event_bus is not None:
            try:
                from app.avatar.runtime.events.types import Event, EventType
                event_obj = Event(
                    type=EventType.TASK_UPDATED,  # Use TASK_UPDATED for narrative events
                    source="narrative_manager",
                    payload={
                        "type": "narrative.update",
                        "payload": event.to_dict(),
                        "session_id": self._session_id,
                    },
                    run_id=self._task_id,
                    step_id=event.step_id,
                )
                logger.debug(f"[NarrativeManager] Sending event {event.event_type} via EventBus")
                self._event_bus.publish(event_obj)
                return
            except Exception as exc:
                logger.warning(
                    "[NarrativeManager] EventBus push failed: %s, falling back to SocketManager",
                    exc,
                )

        # Fallback to SocketManager
        if self._socket_manager is None:
            return

        payload = {
            "type": "narrative.update",
            "payload": event.to_dict(),
        }

        for attempt in range(self.MAX_PUSH_RETRIES):
            try:
                logger.debug(f"[NarrativeManager] Sending event {event.event_type} via SocketManager (attempt {attempt+1})")
                await self._socket_manager.emit(
                    "server_event",
                    payload,
                    room=self._session_id,
                )
                return
            except Exception as exc:
                logger.warning(
                    "[NarrativeManager] push attempt %d failed: %s",
                    attempt + 1, exc,
                )
                if attempt < self.MAX_PUSH_RETRIES - 1:
                    await asyncio.sleep(0.1 * (attempt + 1))

        logger.debug(
            "[NarrativeManager] push failed after retries; "
            "event retained in buffer for replay"
        )

    # ── Legacy interface (backward compatibility) ─────────────────────

    async def on_step_completed(self, description: str) -> None:
        """Legacy: called after each step completes successfully.

        Internally delegates to ``on_event("step.end", ...)``.
        """
        self.narrative.completed.append(description)
        if description in self.narrative.remaining:
            self.narrative.remaining.remove(description)
        self.narrative.repair_hint = None

        await self.on_event(
            "step.end",
            step_id="__run__",
            context=TranslationContext(semantic_label=description),
        )

    async def on_verdict(
        self,
        verdict: str,
        artifacts: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Legacy: called after CompletionGate returns a verdict.

        Internally delegates to ``on_event()`` with the appropriate
        verification event type.
        """
        self.narrative.verification_result = VERDICT_TRANSLATIONS.get(
            verdict, verdict,
        )
        if artifacts:
            self.narrative.final_artifacts = artifacts
        self.narrative.repair_hint = None

        verdict_lower = verdict.lower()
        if verdict_lower in ("pass", "passed", "completed"):
            event_type = "verification.pass"
        elif verdict_lower in ("fail", "failed", "repair_exhausted"):
            event_type = "verification.fail"
        else:
            event_type = "verification.fail"

        await self.on_event(
            event_type,
            step_id="__run__",
            context=TranslationContext(
                reason=VERDICT_TRANSLATIONS.get(verdict, verdict),
            ),
        )

    async def on_repair_triggered(self, repair_hint: str) -> None:
        """Legacy: called when repair loop is triggered.

        Internally delegates to ``on_event("retry.triggered", ...)``.
        """
        self.narrative.repair_hint = f"正在尝试修复：{repair_hint}"

        await self.on_event(
            "retry.triggered",
            step_id="__run__",
            context=TranslationContext(
                reason=repair_hint,
                retry_count=1,
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Legacy: return the old-style narrative dict."""
        n = self.narrative
        return {
            "goal": n.goal,
            "completed": n.completed,
            "remaining": n.remaining,
            "verification_result": n.verification_result,
            "final_artifacts": n.final_artifacts,
            "repair_hint": n.repair_hint,
            "session_id": n.session_id,
            "task_id": n.task_id,
        }


# ---------------------------------------------------------------------------
# FallbackNarrativeManager — no-op fallback when init fails
# ---------------------------------------------------------------------------

class FallbackNarrativeManager:
    """No-op NarrativeManager used when the real manager fails to initialise.

    Only ``task.completed`` and ``task.failed`` lifecycle events are pushed
    via WebSocket.  All other events are silently ignored.

    This ensures GraphController always holds a manager instance (normal or
    fallback) and never needs a ``narrative_manager is None`` branch.
    """

    _LIFECYCLE_EVENTS = frozenset({"task.completed", "task.failed"})
    MAX_PUSH_RETRIES = 3

    def __init__(
        self,
        session_id: str,
        task_id: str,
        socket_manager: Optional[Any] = None,
        event_bus: Optional[Any] = None,
    ) -> None:
        self._session_id = session_id
        self._task_id = task_id
        self._socket_manager = socket_manager
        self._event_bus = event_bus

    async def on_event(
        self,
        internal_event_type: str,
        step_id: str,
        context: TranslationContext,
    ) -> None:
        """Only push task.completed / task.failed; silently ignore the rest."""
        if internal_event_type not in self._LIFECYCLE_EVENTS:
            return

        # Build a minimal payload for lifecycle events
        if internal_event_type == "task.completed":
            description = "任务完成"
            status = "completed"
            event_type = "task_completed"
            phase = "completed"
        else:
            reason = context.reason or context.error_message or "未知错误"
            description = f"任务失败：{reason}"
            status = "failed"
            event_type = "task_failed"
            phase = "completed"

        # First try EventBus
        if self._event_bus is not None:
            try:
                from app.avatar.runtime.events.types import Event, EventType
                event_obj = Event(
                    type=EventType.TASK_UPDATED,
                    source="fallback_narrative_manager",
                    payload={
                        "type": "narrative.update",
                        "payload": {
                            "event_id": str(uuid.uuid4()),
                            "run_id": self._task_id,
                            "step_id": "__run__",
                            "event_type": event_type,
                            "source_event_type": internal_event_type,
                            "level": "major",
                            "phase": phase,
                            "status": status,
                            "description": description,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "sequence": 1,
                            "metadata": {},
                        },
                        "session_id": self._session_id,
                    },
                    run_id=self._task_id,
                    step_id="__run__",
                )
                self._event_bus.publish(event_obj)
                return
            except Exception as exc:
                logger.warning(
                    "[FallbackNarrativeManager] EventBus push failed: %s, falling back to SocketManager",
                    exc,
                )

        # Fallback to SocketManager
        payload = {
            "type": "narrative.update",
            "payload": {
                "event_id": str(uuid.uuid4()),
                "run_id": self._task_id,
                "step_id": "__run__",
                "event_type": event_type,
                "source_event_type": internal_event_type,
                "level": "major",
                "phase": phase,
                "status": status,
                "description": description,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "sequence": 1,
                "metadata": {},
            },
        }

        await self._push(payload)

    async def _push(self, payload: dict) -> None:
        """Push with retry, same contract as NarrativeManager."""
        if self._socket_manager is None:
            return
        for attempt in range(self.MAX_PUSH_RETRIES):
            try:
                await self._socket_manager.emit(
                    "server_event",
                    payload,
                    room=self._session_id,
                )
                return
            except Exception as exc:
                logger.warning(
                    "[FallbackNarrativeManager] push attempt %d failed: %s",
                    attempt + 1, exc,
                )
                if attempt < self.MAX_PUSH_RETRIES - 1:
                    await asyncio.sleep(0.1 * (attempt + 1))

    # ── Legacy interface stubs ────────────────────────────────────────

    async def on_step_completed(self, description: str) -> None:
        """No-op for fallback."""

    async def on_verdict(
        self,
        verdict: str,
        artifacts: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """No-op for fallback."""

    async def on_repair_triggered(self, repair_hint: str) -> None:
        """No-op for fallback."""

    async def replay_after(self, after_sequence: int) -> list[dict]:
        """No buffer in fallback — always returns empty list."""
        return []

    def to_dict(self) -> Dict[str, Any]:
        """Legacy: return empty narrative dict."""
        return {
            "goal": "",
            "completed": [],
            "remaining": [],
            "verification_result": None,
            "final_artifacts": [],
            "repair_hint": None,
            "session_id": self._session_id,
            "task_id": self._task_id,
        }
