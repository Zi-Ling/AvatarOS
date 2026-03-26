# server/app/services/artifact_store.py
"""
ArtifactStore — ArtifactVersionRecord 持久化

产物版本记录管理：注册产物（自动递增版本号）、查询、更新 stale 状态。
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlmodel import Session, select

from app.db.database import engine
from app.db.long_task_models import ArtifactVersionRecord

logger = logging.getLogger(__name__)


class ArtifactStore:
    """ArtifactVersionRecord CRUD"""

    # ------------------------------------------------------------------
    # 注册产物
    # ------------------------------------------------------------------

    @staticmethod
    def register_artifact(
        task_session_id: str,
        artifact_path: str,
        artifact_kind: str,
        producer_step_id: str,
        content_hash: str,
        size: int,
        mtime: float,
        version_source: str = "initial",
    ) -> ArtifactVersionRecord:
        """
        注册产物版本。同一 task_session + artifact_path 下自动递增版本号。
        自动链接 parent_version_id 到上一版本。
        """
        with Session(engine) as db:
            # 查找同路径最新版本以确定新版本号
            latest = db.exec(
                select(ArtifactVersionRecord)
                .where(ArtifactVersionRecord.task_session_id == task_session_id)
                .where(ArtifactVersionRecord.artifact_path == artifact_path)
                .order_by(ArtifactVersionRecord.version.desc())  # type: ignore[attr-defined]
            ).first()

            new_version = (latest.version + 1) if latest else 1
            parent_id = latest.id if latest else None

            # v2+ 默认 version_source 为 iteration（除非调用方显式指定）
            if new_version > 1 and version_source == "initial":
                version_source = "iteration"

            obj = ArtifactVersionRecord(
                task_session_id=task_session_id,
                artifact_path=artifact_path,
                artifact_kind=artifact_kind,
                producer_step_id=producer_step_id,
                version=new_version,
                content_hash=content_hash,
                size=size,
                mtime=mtime,
                parent_version_id=parent_id,
                version_source=version_source,
            )
            db.add(obj)
            db.commit()
            db.refresh(obj)

        logger.info(
            f"[ArtifactStore] Registered artifact {artifact_path} "
            f"v{new_version} (parent={parent_id}, source={version_source}) "
            f"for task_session {task_session_id}"
        )
        return obj

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    @staticmethod
    def get(artifact_id: str) -> Optional[ArtifactVersionRecord]:
        with Session(engine) as db:
            return db.get(ArtifactVersionRecord, artifact_id)

    @staticmethod
    def get_by_path(
        task_session_id: str, artifact_path: str
    ) -> list[ArtifactVersionRecord]:
        """获取同路径所有版本，按版本号降序。"""
        with Session(engine) as db:
            return list(
                db.exec(
                    select(ArtifactVersionRecord)
                    .where(ArtifactVersionRecord.task_session_id == task_session_id)
                    .where(ArtifactVersionRecord.artifact_path == artifact_path)
                    .order_by(ArtifactVersionRecord.version.desc())  # type: ignore[attr-defined]
                ).all()
            )

    @staticmethod
    def get_latest_version(
        task_session_id: str, artifact_path: str
    ) -> Optional[ArtifactVersionRecord]:
        """获取同路径最新版本。"""
        with Session(engine) as db:
            return db.exec(
                select(ArtifactVersionRecord)
                .where(ArtifactVersionRecord.task_session_id == task_session_id)
                .where(ArtifactVersionRecord.artifact_path == artifact_path)
                .order_by(ArtifactVersionRecord.version.desc())  # type: ignore[attr-defined]
            ).first()

    # ------------------------------------------------------------------
    # 更新 stale 状态
    # ------------------------------------------------------------------

    @staticmethod
    def update_stale_status(artifact_id: str, stale_status: Optional[str]) -> None:
        """更新产物的 stale 状态（null / soft_stale / hard_stale）。"""
        with Session(engine) as db:
            obj = db.get(ArtifactVersionRecord, artifact_id)
            if obj:
                obj.stale_status = stale_status
                db.add(obj)
                db.commit()
                logger.info(
                    f"[ArtifactStore] Updated stale_status={stale_status} "
                    f"for artifact {artifact_id}"
                )
