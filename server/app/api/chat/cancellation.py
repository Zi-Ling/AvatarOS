# app/api/chat/cancellation.py
"""
TaskControlManager：任务执行控制层
管理活跃的聊天会话和任务的取消/暂停/恢复。

每个活跃任务对应一个 TaskControlHandle，封装：
- cancel_event: threading.Event（供同步检查）
- pause_event:  asyncio.Event（供 GraphController 异步等待，set=运行，clear=暂停）
- status:       running | paused | cancelled（控制层状态，独立于 DB RunStore 状态）
"""
import asyncio
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Optional, Set
import logging

logger = logging.getLogger(__name__)


class TaskControlStatus(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"


@dataclass
class TaskControlHandle:
    """
    单个任务的运行控制句柄。
    GraphController 直接持有此对象，不通过 env_context 传递控制信号。
    """
    task_id: str
    cancel_event: threading.Event = field(default_factory=threading.Event)
    pause_event: Optional[asyncio.Event] = None  # 在 async 上下文中创建
    status: TaskControlStatus = TaskControlStatus.RUNNING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def is_paused(self) -> bool:
        return self.status == TaskControlStatus.PAUSED

    async def wait_if_paused(self) -> bool:
        """
        如果当前处于暂停状态则阻塞等待恢复。
        返回 True 表示已恢复，False 表示未暂停（直接通过）。
        恢复后自动检查取消状态。
        """
        if self.pause_event is None or self.pause_event.is_set():
            return False
        logger.info(f"[TaskControl] Task {self.task_id} paused, waiting for resume...")
        await self.pause_event.wait()
        logger.info(f"[TaskControl] Task {self.task_id} resumed")
        return True

    def request_cancel(self) -> bool:
        """请求取消。幂等：已取消时返回 False。"""
        if self.status == TaskControlStatus.CANCELLED:
            return False
        self.status = TaskControlStatus.CANCELLED
        self.cancel_event.set()
        # 取消时唤醒 pause 等待，避免死锁
        if self.pause_event is not None:
            self.pause_event.set()
        return True

    def request_pause(self) -> bool:
        """请求暂停。幂等：已暂停/已取消时返回 False。"""
        if self.status != TaskControlStatus.RUNNING:
            return False
        if self.pause_event is None:
            return False
        self.status = TaskControlStatus.PAUSED
        self.pause_event.clear()
        return True

    def request_resume(self) -> bool:
        """请求恢复。幂等：非暂停状态时返回 False。"""
        if self.status != TaskControlStatus.PAUSED:
            return False
        if self.pause_event is None:
            return False
        self.status = TaskControlStatus.RUNNING
        self.pause_event.set()
        return True


class TaskControlManager:
    """
    任务执行控制层单例。

    职责：
    - 注册/注销 TaskControlHandle
    - 提供 cancel / pause / resume 操作入口
    - 管理 session → task 映射
    - 管理 Chat 流式输出取消（session cancel）
    """

    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        # Chat 流式输出取消
        # key: session_id, value: threading.Event
        self._active_sessions: Dict[str, threading.Event] = {}

        # 任务控制句柄
        # key: task_id (or alias), value: TaskControlHandle
        self._handles: Dict[str, TaskControlHandle] = {}

        # session → task_ids 映射
        self._session_tasks: Dict[str, Set[str]] = {}

    @classmethod
    def get_instance(cls) -> 'TaskControlManager':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = TaskControlManager()
        return cls._instance

    # ── Session 管理（Chat 流式输出取消）──────────────────────────────────

    def register_session(self, session_id: str) -> threading.Event:
        cancel_event = threading.Event()
        self._active_sessions[session_id] = cancel_event
        logger.debug(f"[TaskControl] 注册会话: {session_id}")
        return cancel_event

    def unregister_session(self, session_id: str) -> None:
        self._active_sessions.pop(session_id, None)
        logger.debug(f"[TaskControl] 注销会话: {session_id}")

    def cancel_session(self, session_id: str) -> bool:
        event = self._active_sessions.get(session_id)
        if event is None:
            logger.warning(f"[TaskControl] 会话不存在或已结束: {session_id}")
            return False
        event.set()
        logger.info(f"[TaskControl] 已取消会话: {session_id}")
        return True

    def is_session_cancelled(self, session_id: str) -> bool:
        event = self._active_sessions.get(session_id)
        return event.is_set() if event else False

    # ── Task 控制句柄管理 ─────────────────────────────────────────────────

    def register_task(self, task_id: str, session_id: Optional[str] = None) -> TaskControlHandle:
        """
        注册任务，返回 TaskControlHandle。
        pause_event 在当前 async 上下文中创建（需在 async 函数中调用）。
        """
        # 尝试在当前 event loop 中创建 asyncio.Event
        pause_event: Optional[asyncio.Event] = None
        try:
            asyncio.get_running_loop()
            pause_event = asyncio.Event()
            pause_event.set()  # 初始：运行中
        except RuntimeError:
            pass  # 非 async 上下文，pause 功能不可用

        handle = TaskControlHandle(
            task_id=task_id,
            pause_event=pause_event,
        )
        self._handles[task_id] = handle

        if session_id:
            self._session_tasks.setdefault(session_id, set()).add(task_id)

        logger.debug(f"[TaskControl] 注册任务: {task_id} (session: {session_id})")
        return handle

    def alias_task(self, alias_id: str, task_id: str) -> bool:
        """
        为已注册任务添加别名（graph_id → intent_id）。
        别名共享同一个 TaskControlHandle。
        """
        handle = self._handles.get(task_id)
        if handle is None:
            logger.warning(f"[TaskControl] alias_task: task {task_id} not found")
            return False
        self._handles[alias_id] = handle
        logger.debug(f"[TaskControl] 注册别名: {alias_id} → {task_id}")
        return True

    def unregister_task(self, task_id: str) -> None:
        """注销任务，清理句柄和会话映射。"""
        self._handles.pop(task_id, None)
        for task_ids in self._session_tasks.values():
            task_ids.discard(task_id)
        logger.debug(f"[TaskControl] 注销任务: {task_id}")

    def get_handle(self, task_id: str) -> Optional[TaskControlHandle]:
        return self._handles.get(task_id)

    # ── 控制操作（幂等） ──────────────────────────────────────────────────

    def cancel_task(self, task_id: str) -> tuple[bool, str, str]:
        """
        取消任务。幂等。
        返回 (accepted, previous_status, current_status)
        """
        handle = self._handles.get(task_id)
        if handle is None:
            return False, "unknown", "unknown"
        prev = handle.status.value
        accepted = handle.request_cancel()
        return accepted, prev, handle.status.value

    def pause_task(self, task_id: str) -> tuple[bool, str, str]:
        """
        暂停任务。幂等。
        返回 (accepted, previous_status, current_status)
        """
        handle = self._handles.get(task_id)
        if handle is None:
            return False, "unknown", "unknown"
        prev = handle.status.value
        accepted = handle.request_pause()
        return accepted, prev, handle.status.value

    def resume_task(self, task_id: str) -> tuple[bool, str, str]:
        """
        恢复任务。幂等。
        返回 (accepted, previous_status, current_status)
        """
        handle = self._handles.get(task_id)
        if handle is None:
            return False, "unknown", "unknown"
        prev = handle.status.value
        accepted = handle.request_resume()
        return accepted, prev, handle.status.value

    # ── 兼容旧接口（供未迁移的调用方使用）────────────────────────────────

    def get_task_pause_event(self, task_id: str) -> Optional[asyncio.Event]:
        handle = self._handles.get(task_id)
        return handle.pause_event if handle else None

    def is_task_cancelled(self, task_id: str) -> bool:
        handle = self._handles.get(task_id)
        return handle.is_cancelled() if handle else False

    def is_task_paused(self, task_id: str) -> bool:
        handle = self._handles.get(task_id)
        return handle.is_paused() if handle else False

    def get_session_tasks(self, session_id: str) -> Set[str]:
        return self._session_tasks.get(session_id, set()).copy()

    def cancel_all_session_tasks(self, session_id: str) -> int:
        count = 0
        for task_id in self.get_session_tasks(session_id):
            accepted, _, _ = self.cancel_task(task_id)
            if accepted:
                count += 1
        logger.info(f"[TaskControl] 取消了会话 {session_id} 的 {count} 个任务")
        return count

    def get_active_sessions_count(self) -> int:
        return len(self._active_sessions)

    def get_active_tasks_count(self) -> int:
        return len(self._handles)


# ── 全局单例访问 ──────────────────────────────────────────────────────────

_manager: Optional[TaskControlManager] = None


def get_cancellation_manager() -> TaskControlManager:
    """向后兼容别名，返回 TaskControlManager 单例。"""
    global _manager
    if _manager is None:
        _manager = TaskControlManager.get_instance()
    return _manager


def get_task_control_manager() -> TaskControlManager:
    """推荐使用的访问入口。"""
    return get_cancellation_manager()
