"""
HeartbeatManager — 任务心跳定时器管理。

在 DurableStateMixin 中启动/停止，按 heartbeat_interval_s 间隔
更新 TaskSession.last_heartbeat_at，维持 Lease 有效性。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from app.services.task_session_store import TaskSessionStore

logger = logging.getLogger(__name__)


class HeartbeatManager:
    """管理单个任务的心跳定时器"""

    def __init__(self, task_session_id: str, worker_id: str, interval_s: int = 30):
        self.task_session_id = task_session_id
        self.worker_id = worker_id
        self.interval_s = interval_s
        self._task: Optional[asyncio.Task] = None
        self._stopped = False

    async def _heartbeat_loop(self) -> None:
        """心跳循环：定期续约 Lease"""
        while not self._stopped:
            try:
                await asyncio.sleep(self.interval_s)
                if self._stopped:
                    break
                ok = TaskSessionStore.renew_heartbeat(self.task_session_id, self.worker_id)
                if not ok:
                    logger.warning(
                        f"[Heartbeat] Renewal failed for {self.task_session_id}, "
                        f"worker {self.worker_id} — lease may have been taken over"
                    )
                    break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Heartbeat] Error for {self.task_session_id}: {e}")

    def start(self) -> None:
        """启动心跳定时器"""
        if self._task is not None:
            return
        self._stopped = False
        self._task = asyncio.ensure_future(self._heartbeat_loop())
        logger.debug(f"[Heartbeat] Started for {self.task_session_id}")

    def stop(self) -> None:
        """停止心跳定时器"""
        self._stopped = True
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        logger.debug(f"[Heartbeat] Stopped for {self.task_session_id}")
