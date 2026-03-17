# server/app/services/step_state_store.py
"""
StepStateStore — StepState 持久化与状态机管理

StepState 是当前态表（可变），服务恢复和查询。
状态机转换使用条件更新防竞态，复用 state_machines.py 中的合法转换表。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select, text

from app.db.database import engine
from app.db.long_task_models import StepState
from app.avatar.runtime.graph.models.state_machines import (
    VALID_STEP_NODE_TRANSITIONS,
    validate_transition,
    InvalidTransitionError,
    fire_transition_hooks,
)

logger = logging.getLogger(__name__)


class StepStateStore:
    """StepState CRUD + 状态机"""

    # ------------------------------------------------------------------
    # Upsert
    # ------------------------------------------------------------------

    @staticmethod
    def upsert(step_state: StepState) -> StepState:
        """插入或更新 StepState。"""
        with Session(engine) as db:
            existing = db.get(StepState, step_state.id)
            if existing:
                # 更新所有字段
                existing.task_session_id = step_state.task_session_id
                existing.graph_version = step_state.graph_version
                existing.status = step_state.status
                existing.capability_name = step_state.capability_name
                existing.input_snapshot_json = step_state.input_snapshot_json
                existing.output_json = step_state.output_json
                existing.side_effect_summary_json = step_state.side_effect_summary_json
                existing.error_message = step_state.error_message
                existing.retry_count = step_state.retry_count
                existing.last_heartbeat_at = step_state.last_heartbeat_at
                existing.heartbeat_interval_s = step_state.heartbeat_interval_s
                existing.stale_threshold_s = step_state.stale_threshold_s
                existing.started_at = step_state.started_at
                existing.ended_at = step_state.ended_at
                existing.updated_at = datetime.now(timezone.utc)
                db.add(existing)
                db.commit()
                db.refresh(existing)
                return existing
            else:
                step_state.updated_at = datetime.now(timezone.utc)
                db.add(step_state)
                db.commit()
                db.refresh(step_state)
                return step_state

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    @staticmethod
    def get(step_id: str) -> Optional[StepState]:
        with Session(engine) as db:
            return db.get(StepState, step_id)

    @staticmethod
    def get_by_task_session(task_session_id: str) -> list[StepState]:
        with Session(engine) as db:
            return list(
                db.exec(
                    select(StepState).where(
                        StepState.task_session_id == task_session_id
                    )
                ).all()
            )

    # ------------------------------------------------------------------
    # 状态转换（带条件更新防竞态）
    # ------------------------------------------------------------------

    @staticmethod
    def transition(step_id: str, new_status: str, **kwargs) -> None:
        """
        状态机转换。

        - 非法转换：抛 InvalidTransitionError
        - 竞态（条件更新 0 行）：抛 InvalidTransitionError
        - kwargs 可携带额外字段更新（error_message、output_json 等）
        """
        with Session(engine) as db:
            obj = db.get(StepState, step_id)
            if not obj:
                raise InvalidTransitionError("step_node", "unknown", new_status)

            current = obj.status
            if not validate_transition(current, new_status, VALID_STEP_NODE_TRANSITIONS):
                raise InvalidTransitionError("step_node", current, new_status)

            now = datetime.now(timezone.utc)

            # 条件更新：WHERE id=? AND status=current
            result = db.exec(
                text(
                    "UPDATE step_states SET status=:new_status, updated_at=:now "
                    "WHERE id=:sid AND status=:cur_status"
                ).bindparams(
                    new_status=new_status, now=now,
                    sid=step_id, cur_status=current,
                )
            )
            if result.rowcount == 0:
                raise InvalidTransitionError("step_node", current, new_status)

            # 更新时间戳和附加字段
            obj = db.get(StepState, step_id)
            if new_status == "running" and obj.started_at is None:
                obj.started_at = now
            elif new_status in ("success", "failed", "cancelled", "skipped"):
                obj.ended_at = now

            for k, v in kwargs.items():
                if hasattr(obj, k):
                    setattr(obj, k, v)

            db.add(obj)
            db.commit()

        # 钩子在事务提交后触发
        fire_transition_hooks("step_node", step_id, current, new_status)
        logger.info(f"[StepStateStore] step {step_id}: {current} -> {new_status}")

    # ------------------------------------------------------------------
    # 心跳更新
    # ------------------------------------------------------------------

    @staticmethod
    def update_heartbeat(step_id: str) -> None:
        """更新 last_heartbeat_at 为当前时间。"""
        now = datetime.now(timezone.utc)
        with Session(engine) as db:
            obj = db.get(StepState, step_id)
            if obj:
                obj.last_heartbeat_at = now
                obj.updated_at = now
                db.add(obj)
                db.commit()
