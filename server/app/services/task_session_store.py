# server/app/services/task_session_store.py
"""
TaskSessionStore — TaskSession 生命周期管理

状态机转换：非法转换抛 InvalidTransitionError，调用方必须显式处理。
并发防护：transition 使用条件更新（WHERE status=current），更新 0 行说明竞态发生。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select, text

from app.db.database import engine
from app.db.long_task_models import TaskSession
from app.avatar.runtime.graph.models.state_machines import (
    VALID_TASK_SESSION_TRANSITIONS,
    validate_transition,
    InvalidTransitionError,
    fire_transition_hooks,
)

logger = logging.getLogger(__name__)

# 终态集合
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

# TaskEventStream 注册表：task_session_id → TaskEventStream
_event_streams: dict[str, object] = {}


def register_event_stream(task_session_id: str, stream) -> None:
    """注册 TaskEventStream 实例。"""
    _event_streams[task_session_id] = stream


def unregister_event_stream(task_session_id: str) -> None:
    """注销 TaskEventStream 实例。"""
    _event_streams.pop(task_session_id, None)


def _emit_task_session_event(task_session_id: str, old_status: str, new_status: str) -> None:
    stream = _event_streams.get(task_session_id)
    if stream:
        try:
            stream.emit("task_session_transition", {
                "old_status": old_status,
                "new_status": new_status,
            })
        except Exception as e:
            logger.debug(f"[TaskSessionStore] Event emission failed: {e}")


class TaskSessionStore:
    """TaskSession CRUD + 状态机"""

    # ------------------------------------------------------------------
    # 创建
    # ------------------------------------------------------------------

    @staticmethod
    def create(goal: str, config_json: Optional[str] = None) -> TaskSession:
        obj = TaskSession(goal=goal, config_json=config_json)
        with Session(engine) as db:
            db.add(obj)
            db.commit()
            db.refresh(obj)
        logger.info(f"[TaskSessionStore] Created task_session {obj.id}")
        return obj

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    @staticmethod
    def get(task_session_id: str) -> Optional[TaskSession]:
        with Session(engine) as db:
            return db.get(TaskSession, task_session_id)

    @staticmethod
    def get_by_status(status: str) -> list[TaskSession]:
        with Session(engine) as db:
            return list(
                db.exec(select(TaskSession).where(TaskSession.status == status)).all()
            )

    # ------------------------------------------------------------------
    # 状态转换（带条件更新防竞态）
    # ------------------------------------------------------------------

    @staticmethod
    def transition(task_session_id: str, new_status: str, **kwargs) -> None:
        """
        状态机转换。

        - 非法转换：抛 InvalidTransitionError
        - 竞态（条件更新 0 行）：抛 InvalidTransitionError
        - kwargs 可携带额外字段更新
        """
        with Session(engine) as db:
            obj = db.get(TaskSession, task_session_id)
            if not obj:
                raise InvalidTransitionError("task_session", "unknown", new_status)

            current = obj.status
            if not validate_transition(current, new_status, VALID_TASK_SESSION_TRANSITIONS):
                raise InvalidTransitionError("task_session", current, new_status)

            now = datetime.now(timezone.utc)

            # 条件更新：WHERE id=? AND status=current，防止并发覆盖
            result = db.exec(
                text(
                    "UPDATE task_sessions SET status=:new_status, updated_at=:now "
                    "WHERE id=:sid AND status=:cur_status"
                ).bindparams(
                    new_status=new_status, now=now,
                    sid=task_session_id, cur_status=current,
                )
            )
            if result.rowcount == 0:
                raise InvalidTransitionError("task_session", current, new_status)

            # 更新终态时间戳和附加字段
            obj = db.get(TaskSession, task_session_id)
            if new_status in _TERMINAL_STATUSES:
                obj.completed_at = now

            for k, v in kwargs.items():
                if hasattr(obj, k):
                    setattr(obj, k, v)

            db.add(obj)
            db.commit()

        # 钩子在事务提交后触发
        fire_transition_hooks("task_session", task_session_id, current, new_status)

        # 事件流发射（如果有注册的 event_stream）
        _emit_task_session_event(task_session_id, current, new_status)

        logger.info(
            f"[TaskSessionStore] task_session {task_session_id}: {current} -> {new_status}"
        )

    # ------------------------------------------------------------------
    # 加载非终态会话
    # ------------------------------------------------------------------

    @staticmethod
    def load_non_terminal() -> list[TaskSession]:
        """加载所有非终态 TaskSession（供恢复流程使用）。"""
        with Session(engine) as db:
            return list(
                db.exec(
                    select(TaskSession).where(
                        TaskSession.status.notin_(_TERMINAL_STATUSES)  # type: ignore[attr-defined]
                    )
                ).all()
            )
