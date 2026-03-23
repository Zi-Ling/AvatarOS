# server/app/services/effect_ledger_store.py
"""
EffectLedgerStore — 副作用账本持久化服务

生命周期状态：prepared → committed / unknown → compensated
用于追踪每个副作用的执行状态，支持恢复时判断跳过/重试/人工确认。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from app.db.database import engine
from app.db.long_task_models import EffectLedgerEntry

logger = logging.getLogger(__name__)

# 合法状态转换
_VALID_EFFECT_TRANSITIONS = {
    "prepared": {"committed", "unknown"},
    "committed": {"compensated"},
    "unknown": {"committed", "compensated"},
}


class EffectLedgerStore:
    """EffectLedgerEntry CRUD + 状态转换"""

    @staticmethod
    def prepare(
        task_session_id: str,
        step_id: str,
        effect_type: str,
        target_path: Optional[str] = None,
        external_request_id: Optional[str] = None,
        metadata_json: Optional[str] = None,
    ) -> EffectLedgerEntry:
        """注册一个 prepared 状态的副作用条目（执行前调用）。"""
        entry = EffectLedgerEntry(
            task_session_id=task_session_id,
            step_id=step_id,
            effect_type=effect_type,
            status="prepared",
            target_path=target_path,
            external_request_id=external_request_id,
            metadata_json=metadata_json,
        )
        with Session(engine) as db:
            db.add(entry)
            db.commit()
            db.refresh(entry)
        logger.info(f"[EffectLedger] Prepared: {entry.id} type={effect_type}")
        return entry

    @staticmethod
    def commit(
        entry_id: str,
        content_hash: Optional[str] = None,
        remote_receipt: Optional[str] = None,
    ) -> bool:
        """将副作用标记为 committed（执行成功后调用）。"""
        return EffectLedgerStore._transition(
            entry_id, "committed",
            content_hash=content_hash,
            remote_receipt=remote_receipt,
        )

    @staticmethod
    def mark_unknown(entry_id: str) -> bool:
        """将副作用标记为 unknown（执行结果不确定时调用）。"""
        return EffectLedgerStore._transition(entry_id, "unknown")

    @staticmethod
    def compensate(entry_id: str, compensation_details: str) -> bool:
        """将副作用标记为 compensated（补偿操作完成后调用）。"""
        return EffectLedgerStore._transition(
            entry_id, "compensated",
            compensation_details=compensation_details,
        )

    @staticmethod
    def _transition(entry_id: str, new_status: str, **kwargs) -> bool:
        """内部状态转换，校验合法性。"""
        now = datetime.now(timezone.utc)
        with Session(engine) as db:
            entry = db.get(EffectLedgerEntry, entry_id)
            if not entry:
                logger.warning(f"[EffectLedger] Entry not found: {entry_id}")
                return False

            valid_targets = _VALID_EFFECT_TRANSITIONS.get(entry.status, set())
            if new_status not in valid_targets:
                logger.warning(
                    f"[EffectLedger] Invalid transition: {entry.status} -> {new_status} "
                    f"for entry {entry_id}"
                )
                return False

            entry.status = new_status
            entry.updated_at = now
            for k, v in kwargs.items():
                if v is not None and hasattr(entry, k):
                    setattr(entry, k, v)

            db.add(entry)
            db.commit()

        logger.info(f"[EffectLedger] {entry_id}: -> {new_status}")
        return True

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    @staticmethod
    def get(entry_id: str) -> Optional[EffectLedgerEntry]:
        with Session(engine) as db:
            return db.get(EffectLedgerEntry, entry_id)

    @staticmethod
    def get_by_task(task_session_id: str) -> list[EffectLedgerEntry]:
        with Session(engine) as db:
            return list(
                db.exec(
                    select(EffectLedgerEntry)
                    .where(EffectLedgerEntry.task_session_id == task_session_id)
                    .order_by(EffectLedgerEntry.created_at)  # type: ignore[attr-defined]
                ).all()
            )

    @staticmethod
    def get_by_step(task_session_id: str, step_id: str) -> list[EffectLedgerEntry]:
        with Session(engine) as db:
            return list(
                db.exec(
                    select(EffectLedgerEntry)
                    .where(EffectLedgerEntry.task_session_id == task_session_id)
                    .where(EffectLedgerEntry.step_id == step_id)
                    .order_by(EffectLedgerEntry.created_at)  # type: ignore[attr-defined]
                ).all()
            )

    @staticmethod
    def get_unknown_effects(task_session_id: str) -> list[EffectLedgerEntry]:
        """获取所有 unknown 状态的副作用（需要人工确认）。"""
        with Session(engine) as db:
            return list(
                db.exec(
                    select(EffectLedgerEntry)
                    .where(EffectLedgerEntry.task_session_id == task_session_id)
                    .where(EffectLedgerEntry.status == "unknown")
                ).all()
            )
