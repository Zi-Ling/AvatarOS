# server/app/services/checkpoint_store.py
"""
CheckpointStore — Checkpoint 持久化

四级重要性：routine / milestone / merge / pre_risky
支持软删除（保留策略使用）。
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlmodel import Session, select

from app.db.database import engine
from app.db.long_task_models import Checkpoint

logger = logging.getLogger(__name__)


class CheckpointStore:
    """Checkpoint CRUD + 软删除"""

    # ------------------------------------------------------------------
    # 创建
    # ------------------------------------------------------------------

    @staticmethod
    def create(
        task_session_id: str,
        importance: str,
        reason: str,
        graph_snapshot_json: str,
        step_states_json: str,
        artifact_refs_json: str,
        checksum: str,
        graph_version: int,
        budget_info_json: Optional[str] = None,
        environment_snapshot_json: Optional[str] = None,
        execution_frontier_json: Optional[str] = None,
        idempotency_metadata_json: Optional[str] = None,
        effect_ledger_snapshot_json: Optional[str] = None,
        pending_requests_json: Optional[str] = None,
    ) -> Checkpoint:
        obj = Checkpoint(
            task_session_id=task_session_id,
            importance=importance,
            reason=reason,
            graph_snapshot_json=graph_snapshot_json,
            step_states_json=step_states_json,
            artifact_refs_json=artifact_refs_json,
            checksum=checksum,
            graph_version=graph_version,
            budget_info_json=budget_info_json,
            environment_snapshot_json=environment_snapshot_json,
            execution_frontier_json=execution_frontier_json,
            idempotency_metadata_json=idempotency_metadata_json,
            effect_ledger_snapshot_json=effect_ledger_snapshot_json,
            pending_requests_json=pending_requests_json,
        )
        with Session(engine) as db:
            db.add(obj)
            db.commit()
            db.refresh(obj)
        logger.info(
            f"[CheckpointStore] Created checkpoint {obj.id} "
            f"importance={importance} for task_session {task_session_id}"
        )
        return obj

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    @staticmethod
    def get(checkpoint_id: str) -> Optional[Checkpoint]:
        with Session(engine) as db:
            return db.get(Checkpoint, checkpoint_id)

    @staticmethod
    def get_by_task_session(task_session_id: str) -> list[Checkpoint]:
        """获取指定 task_session 的所有未删除 checkpoint，按创建时间降序。"""
        with Session(engine) as db:
            return list(
                db.exec(
                    select(Checkpoint)
                    .where(Checkpoint.task_session_id == task_session_id)
                    .where(Checkpoint.is_deleted == False)  # noqa: E712
                    .order_by(Checkpoint.created_at.desc())  # type: ignore[attr-defined]
                ).all()
            )

    @staticmethod
    def get_latest_valid(task_session_id: str) -> Optional[Checkpoint]:
        """获取最近的未删除 checkpoint。"""
        with Session(engine) as db:
            return db.exec(
                select(Checkpoint)
                .where(Checkpoint.task_session_id == task_session_id)
                .where(Checkpoint.is_deleted == False)  # noqa: E712
                .order_by(Checkpoint.created_at.desc())  # type: ignore[attr-defined]
            ).first()

    # ------------------------------------------------------------------
    # 软删除
    # ------------------------------------------------------------------

    @staticmethod
    def soft_delete(checkpoint_id: str) -> None:
        """软删除 checkpoint（设置 is_deleted=True）。"""
        with Session(engine) as db:
            obj = db.get(Checkpoint, checkpoint_id)
            if obj:
                obj.is_deleted = True
                db.add(obj)
                db.commit()
                logger.info(f"[CheckpointStore] Soft-deleted checkpoint {checkpoint_id}")

    # ------------------------------------------------------------------
    # 清理策略
    # ------------------------------------------------------------------

    # 需要保留的重要级别（不参与 routine 清理）
    _PRESERVE_IMPORTANCE = {
        "milestone", "merge", "pre_risky",
        "failure_snapshot", "state_transition",
    }

    @staticmethod
    def cleanup_old_checkpoints(
        task_session_id: str,
        max_routine: int = 20,
        preserve_importance: Optional[set] = None,
    ) -> int:
        """
        清理超出上限的 routine 级别 checkpoint。

        保留所有重要级别（milestone/failure_snapshot/state_transition 等），
        仅对 routine/pre_effect/post_effect 级别执行 FIFO 清理。

        Returns:
            被软删除的 checkpoint 数量
        """
        if preserve_importance is None:
            preserve_importance = CheckpointStore._PRESERVE_IMPORTANCE

        cleanable_levels = {"routine", "pre_effect", "post_effect"}

        with Session(engine) as db:
            all_cleanable = list(
                db.exec(
                    select(Checkpoint)
                    .where(Checkpoint.task_session_id == task_session_id)
                    .where(Checkpoint.is_deleted == False)  # noqa: E712
                    .where(Checkpoint.importance.in_(cleanable_levels))  # type: ignore[attr-defined]
                    .order_by(Checkpoint.created_at.desc())  # type: ignore[attr-defined]
                ).all()
            )

            if len(all_cleanable) <= max_routine:
                return 0

            to_delete = all_cleanable[max_routine:]
            for cp in to_delete:
                cp.is_deleted = True
                db.add(cp)

            db.commit()
            deleted = len(to_delete)

        if deleted > 0:
            logger.info(
                f"[CheckpointStore] Cleaned up {deleted} routine checkpoints "
                f"for task_session {task_session_id}"
            )
        return deleted
