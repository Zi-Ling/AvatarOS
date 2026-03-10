# server/app/avatar/runtime/storage/file_registry.py
"""
FileRegistry — workspace 文件产物的元信息注册表

存储在 avatar.db（~/.avatar/avatar.db），与其他系统表统一管理。
不存文件内容，只存元信息索引。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class FileRegistry:
    """
    文件产物注册表，使用 avatar.db（SQLModel engine）。

    使用方式：
        registry = FileRegistry()
        registry.register(file_path, sha256, size, mime, source_url, skill_name=skill_name)
    """

    def __init__(self):
        from app.db.database import engine
        from app.db.file_artifact import FileArtifact
        from sqlmodel import SQLModel
        # 确保表已创建（init_db 会调用，这里做兜底）
        SQLModel.metadata.create_all(engine, tables=[FileArtifact.__table__])
        self._engine = engine
        logger.debug("[FileRegistry] Initialized (avatar.db)")

    # ── 写入 ──────────────────────────────────────────────────────────────────

    def register(
        self,
        file_path: Path,
        sha256: str,
        size: int,
        mime_type: str = "",
        source_url: str = "",
        task_id: str = "",
        node_id: str = "",
        skill_name: str = "",
        lifecycle: str = "intermediate",
    ):
        """
        注册一个文件产物（幂等）。

        - 同 file_path + 同 sha256 → 跳过
        - 同 file_path + 不同 sha256 → 更新
        - 新 file_path → 插入
        """
        from app.db.file_artifact import FileArtifact
        from sqlmodel import Session, select

        file_path = Path(file_path)
        filename = file_path.name
        now = datetime.now(timezone.utc).isoformat()

        with Session(self._engine) as session:
            existing = session.exec(
                select(FileArtifact).where(FileArtifact.file_path == str(file_path))
            ).first()

            if existing:
                if existing.sha256 == sha256:
                    logger.debug(f"[FileRegistry] Skipped (identical): {filename}")
                    return existing
                # 覆盖写入
                existing.sha256 = sha256
                existing.size = size
                existing.mime_type = mime_type
                existing.source_url = source_url
                existing.task_id = task_id
                existing.node_id = node_id
                existing.skill_name = skill_name
                existing.created_at = now
                existing.lifecycle = lifecycle
                session.add(existing)
                session.commit()
                session.refresh(existing)
                logger.debug(f"[FileRegistry] Updated (overwritten): {filename}")
                return existing

            artifact = FileArtifact(
                artifact_id=str(uuid.uuid4()),
                file_path=str(file_path),
                filename=filename,
                sha256=sha256,
                size=size,
                mime_type=mime_type,
                source_url=source_url,
                task_id=task_id,
                node_id=node_id,
                skill_name=skill_name,
                created_at=now,
                lifecycle=lifecycle,
            )
            session.add(artifact)
            session.commit()
            session.refresh(artifact)
            logger.debug(f"[FileRegistry] Registered: {filename} ({sha256[:12]})")
            return artifact

    # ── 查询 ──────────────────────────────────────────────────────────────────

    def get_by_sha256(self, sha256: str):
        from app.db.file_artifact import FileArtifact
        from sqlmodel import Session, select
        with Session(self._engine) as session:
            return session.exec(
                select(FileArtifact).where(FileArtifact.sha256 == sha256)
                .order_by(FileArtifact.created_at.desc())
            ).all()

    def get_by_source_url(self, source_url: str):
        from app.db.file_artifact import FileArtifact
        from sqlmodel import Session, select
        with Session(self._engine) as session:
            return session.exec(
                select(FileArtifact).where(FileArtifact.source_url == source_url)
                .order_by(FileArtifact.created_at.desc())
            ).all()

    def get_by_task_id(self, task_id: str):
        from app.db.file_artifact import FileArtifact
        from sqlmodel import Session, select
        with Session(self._engine) as session:
            return session.exec(
                select(FileArtifact).where(FileArtifact.task_id == task_id)
                .order_by(FileArtifact.created_at.desc())
            ).all()

    def query_by_time_range(
        self,
        since: datetime,
        until: Optional[datetime] = None,
        mime_prefix: Optional[str] = None,
        skill_name: Optional[str] = None,
        limit: int = 200,
    ):
        from app.db.file_artifact import FileArtifact
        from sqlmodel import Session, select
        until = until or datetime.now(timezone.utc)
        with Session(self._engine) as session:
            stmt = (
                select(FileArtifact)
                .where(FileArtifact.created_at >= since.isoformat())
                .where(FileArtifact.created_at <= until.isoformat())
            )
            if mime_prefix:
                stmt = stmt.where(FileArtifact.mime_type.startswith(mime_prefix))
            if skill_name:
                stmt = stmt.where(FileArtifact.skill_name == skill_name)
            stmt = stmt.order_by(FileArtifact.created_at.desc()).limit(limit)
            return session.exec(stmt).all()

    def mark_final(self, file_path: Path) -> None:
        from app.db.file_artifact import FileArtifact
        from sqlmodel import Session, select
        with Session(self._engine) as session:
            artifact = session.exec(
                select(FileArtifact).where(FileArtifact.file_path == str(file_path))
            ).first()
            if artifact:
                artifact.lifecycle = "final"
                session.add(artifact)
                session.commit()
