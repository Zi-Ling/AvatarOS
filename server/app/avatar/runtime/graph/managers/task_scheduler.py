# server/app/avatar/runtime/graph/managers/task_scheduler.py
"""
TaskScheduler — 多任务调度器

- 两类槽位：long_task (默认 1) 和 simple_task (默认 2)
- 优先级模型：priority_class (user_explicit > resume > system_maintenance)
  + 同 class 内 FIFO (按 enqueued_at)
- paused/interrupted 长任务不阻塞简单任务槽位

任务隔离：
- 每个 TaskSession 通过 task_session_id 在 TaskQueueEntry 中隔离
- 独立 workspace 目录、独立 Plan_Graph、独立 Artifact 命名空间
- 独立 event stream（不交叉）、独立 task-local memory（不共享）
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Priority class → numeric level mapping
PRIORITY_LEVELS: dict[str, int] = {
    "user_explicit": 1,
    "resume": 2,
    "system_maintenance": 3,
}


class TaskScheduler:
    """多任务调度器。"""

    def __init__(self, long_task_slots: int = 1, simple_task_slots: int = 2, event_stream_registry=None):
        self._long_task_slots = long_task_slots
        self._simple_task_slots = simple_task_slots
        # In-memory queue: list of dicts
        self._queue: list[dict] = []
        # Running tasks: task_session_id → task_type
        self._running: dict[str, str] = {}
        # Optional: callable(task_session_id) → TaskEventStream
        self._event_stream_registry = event_stream_registry

    async def enqueue(
        self,
        task_session_id: str,
        task_type: str,
        priority_class: str = "user_explicit",
    ) -> None:
        """
        入队任务。

        priority_class: user_explicit / resume / system_maintenance
        task_type: long_task / simple_task
        """
        level = PRIORITY_LEVELS.get(priority_class, 3)
        entry = {
            "task_session_id": task_session_id,
            "task_type": task_type,
            "priority_level": level,
            "priority_class": priority_class,
            "enqueued_at": datetime.now(timezone.utc),
        }
        self._queue.append(entry)

        # Sort queue: by priority_level ASC, then enqueued_at ASC (FIFO within class)
        self._queue.sort(key=lambda e: (e["priority_level"], e["enqueued_at"]))

        logger.info(
            f"[TaskScheduler] Enqueued {task_session_id} "
            f"type={task_type} priority={priority_class} "
            f"(queue size={len(self._queue)})"
        )

    async def try_acquire_slot(self, task_type: str) -> bool:
        """
        尝试获取槽位。

        Returns:
            True if slot acquired, False if no slot available.
        """
        running_count = self._count_running_by_type(task_type)

        if task_type == "long_task":
            if running_count < self._long_task_slots:
                return True
            logger.debug(
                f"[TaskScheduler] No long_task slot available "
                f"({running_count}/{self._long_task_slots})"
            )
            return False
        else:
            if running_count < self._simple_task_slots:
                return True
            logger.debug(
                f"[TaskScheduler] No simple_task slot available "
                f"({running_count}/{self._simple_task_slots})"
            )
            return False

    async def release_slot(self, task_session_id: str) -> None:
        """释放槽位。"""
        if task_session_id in self._running:
            task_type = self._running.pop(task_session_id)
            logger.info(
                f"[TaskScheduler] Released slot for {task_session_id} "
                f"(type={task_type})"
            )
            self._emit_event(task_session_id, "slot_released", {"task_type": task_type})
        else:
            logger.warning(
                f"[TaskScheduler] Task {task_session_id} not found in running set"
            )

        # Remove from queue if still queued
        self._queue = [
            e for e in self._queue
            if e["task_session_id"] != task_session_id
        ]

    def get_running_count(self) -> dict:
        """返回 {long_task: N, simple_task: M}。"""
        long_count = self._count_running_by_type("long_task")
        simple_count = self._count_running_by_type("simple_task")
        return {"long_task": long_count, "simple_task": simple_count}

    def _count_running_by_type(self, task_type: str) -> int:
        """Count running tasks of a specific type."""
        return sum(1 for t in self._running.values() if t == task_type)

    def _mark_running(self, task_session_id: str, task_type: str) -> None:
        """Mark a task as running (internal helper for slot tracking)."""
        self._running[task_session_id] = task_type
        logger.info(
            f"[TaskScheduler] Marked {task_session_id} as running "
            f"(type={task_type})"
        )
        self._emit_event(task_session_id, "slot_acquired", {"task_type": task_type})

    def _emit_event(self, task_session_id: str, event_type: str, payload: dict) -> None:
        if self._event_stream_registry:
            try:
                stream = self._event_stream_registry(task_session_id)
                if stream:
                    stream.emit(event_type, payload)
            except Exception as e:
                logger.debug(f"[TaskScheduler] Event emission failed: {e}")
