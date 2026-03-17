# server/app/services/plan_graph_store.py
"""
PlanGraphStore — Plan Graph Snapshot + Patch Log 持久化

快照 + Patch Log 双轨制：
- 定期保存完整快照（initial_plan / post_merge / pre_resume / periodic）
- append-only Patch Log 记录每次变更操作
- 支持从快照 + 后续 Patch Log 重建任意版本
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlmodel import Session, select

from app.db.database import engine
from app.db.long_task_models import PlanGraphSnapshot, PatchLogEntry

logger = logging.getLogger(__name__)

# TaskEventStream 注册表：task_session_id → TaskEventStream
_event_streams: dict[str, object] = {}


def register_event_stream(task_session_id: str, stream) -> None:
    _event_streams[task_session_id] = stream


def unregister_event_stream(task_session_id: str) -> None:
    _event_streams.pop(task_session_id, None)


def _emit_graph_event(task_session_id: str, event_type: str, payload: dict) -> None:
    stream = _event_streams.get(task_session_id)
    if stream:
        try:
            stream.emit(event_type, payload)
        except Exception as e:
            logger.debug(f"[PlanGraphStore] Event emission failed: {e}")


class PlanGraphStore:
    """PlanGraph Snapshot + PatchLog CRUD"""

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    @staticmethod
    def save_snapshot(
        task_session_id: str,
        graph_version: int,
        graph_json: str,
        snapshot_reason: str,
        change_source: str = "system",
    ) -> PlanGraphSnapshot:
        obj = PlanGraphSnapshot(
            task_session_id=task_session_id,
            graph_version=graph_version,
            graph_json=graph_json,
            snapshot_reason=snapshot_reason,
            change_source=change_source,
        )
        with Session(engine) as db:
            db.add(obj)
            db.commit()
            db.refresh(obj)
        logger.info(
            f"[PlanGraphStore] Saved snapshot v{graph_version} "
            f"for task_session {task_session_id} reason={snapshot_reason}"
        )
        return obj

    @staticmethod
    def get_latest_snapshot(task_session_id: str) -> Optional[PlanGraphSnapshot]:
        with Session(engine) as db:
            return db.exec(
                select(PlanGraphSnapshot)
                .where(PlanGraphSnapshot.task_session_id == task_session_id)
                .order_by(PlanGraphSnapshot.graph_version.desc())  # type: ignore[attr-defined]
            ).first()

    # ------------------------------------------------------------------
    # Patch Log
    # ------------------------------------------------------------------

    @staticmethod
    def append_patch(
        task_session_id: str,
        graph_version: int,
        operation: str,
        operation_params_json: str,
        change_reason: str,
        change_source: str = "system",
        diff_json: Optional[str] = None,
    ) -> PatchLogEntry:
        obj = PatchLogEntry(
            task_session_id=task_session_id,
            graph_version=graph_version,
            operation=operation,
            operation_params_json=operation_params_json,
            change_reason=change_reason,
            change_source=change_source,
            diff_json=diff_json,
        )
        with Session(engine) as db:
            db.add(obj)
            db.commit()
            db.refresh(obj)
        logger.info(
            f"[PlanGraphStore] Appended patch v{graph_version} "
            f"op={operation} for task_session {task_session_id}"
        )
        _emit_graph_event(task_session_id, "graph_version_change", {
            "graph_version": graph_version,
            "operation": operation,
            "change_reason": change_reason,
            "change_source": change_source,
        })
        return obj

    @staticmethod
    def get_patches_since(
        task_session_id: str, since_version: int
    ) -> list[PatchLogEntry]:
        """获取 graph_version > since_version 的所有 patch，按版本升序。"""
        with Session(engine) as db:
            return list(
                db.exec(
                    select(PatchLogEntry)
                    .where(PatchLogEntry.task_session_id == task_session_id)
                    .where(PatchLogEntry.graph_version > since_version)
                    .order_by(PatchLogEntry.graph_version.asc())  # type: ignore[attr-defined]
                ).all()
            )

    # ------------------------------------------------------------------
    # 重建（占位 — 实际重建逻辑在 GraphController）
    # ------------------------------------------------------------------

    @staticmethod
    def rebuild_from_patches(
        snapshot: PlanGraphSnapshot, patches: list[PatchLogEntry]
    ) -> str:
        """
        占位实现：返回快照的 graph_json。
        实际 patch 应用逻辑将在 GraphController 中实现。
        """
        return snapshot.graph_json
