# server/app/avatar/runtime/graph/events/task_event_stream.py
"""
TaskEventStream — 统一事件流

事件类型：
- task_session_transition
- graph_version_change
- checkpoint_created
- change_merge_completed
- resume_attempt
- stale_propagation
- delivery_gate_result
- heartbeat
- slot_acquired / slot_released

复用现有 EventTraceRecord 的 append-only 机制。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class TaskEventStream:
    """统一事件流，每个 TaskSession 独立实例。支持可选 DB 持久化。"""

    def __init__(self, task_session_id: str, persist_to_db: bool = False):
        self._task_session_id = task_session_id
        self._events: list[dict] = []  # In-memory buffer
        self._persist_to_db = persist_to_db

    def emit(self, event_type: str, payload: dict | None = None) -> None:
        """Emit an event to the stream."""
        event = {
            "task_session_id": self._task_session_id,
            "event_type": event_type,
            "payload": payload or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._events.append(event)

        # 可选 DB 持久化（用于审计和事件回源）
        if self._persist_to_db:
            self._persist_event(event)

        logger.info(
            f"[TaskEventStream] {self._task_session_id}: {event_type}"
        )

    def _persist_event(self, event: dict) -> None:
        """将事件持久化到 AuditLog（审计用途）。"""
        try:
            from sqlmodel import Session
            from app.db.database import engine
            from app.db.system import AuditLog

            log = AuditLog(
                event_type=f"task_event.{event['event_type']}",
                resource=self._task_session_id,
                operation=event["event_type"],
                details=event.get("payload"),
            )
            with Session(engine) as db:
                db.add(log)
                db.commit()
        except Exception as e:
            logger.debug(f"[TaskEventStream] DB persist failed (non-fatal): {e}")

    def get_events(
        self, event_type: str | None = None, limit: int = 100
    ) -> list[dict]:
        """Get events, optionally filtered by type."""
        events = self._events
        if event_type:
            events = [e for e in events if e["event_type"] == event_type]
        return events[-limit:]

    def get_all_events(self) -> list[dict]:
        """Get all events in the stream."""
        return list(self._events)
