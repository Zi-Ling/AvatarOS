# app/services/gc_service.py
"""
GC Service — Artifact GC + Session Archiver

ArtifactGC:
  - 扫描 ~/.avatar/sessions/ 下所有 session workspace 目录
  - 删除 completed/failed/archived 且超过 retention_days 的 session 目录
  - 同步清理 ArtifactRecord（storage_uri 文件已不存在的记录标记为 purged）

SessionArchiver:
  - 把 completed/failed 且超过 archive_after_days 的 ExecutionSession 状态改为 archived
  - 不删除 DB 记录，只改 status，防止 DB 膨胀靠 purge 接口手动触发

两者都是幂等操作，可重复调用。
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from sqlmodel import Session, select

from app.db.database import engine
from app.db.system import ExecutionSession
from app.core.config import AVATAR_SESSIONS_DIR

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Artifact GC
# ---------------------------------------------------------------------------

class ArtifactGC:
    """
    清理过期 session workspace 目录（磁盘文件）。

    策略：
    - 只清理 status in (completed, failed, archived, cancelled) 的 session
    - session 的 completed_at / created_at 超过 retention_days 才清理
    - 清理前从 DB 查 workspace_path，确认路径在 AVATAR_SESSIONS_DIR 下（安全校验）
    """

    def __init__(self, retention_days: int = 7):
        self.retention_days = retention_days

    def run(self) -> dict:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        terminal_statuses = {"completed", "failed", "archived", "cancelled"}

        deleted_dirs: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []

        with Session(engine) as db:
            sessions = db.exec(
                select(ExecutionSession).where(
                    ExecutionSession.status.in_(terminal_statuses)
                )
            ).all()

        for s in sessions:
            # 用 completed_at 优先，fallback 到 created_at
            ref_time = s.completed_at or s.created_at
            if ref_time is None:
                continue
            # 确保 timezone-aware
            if ref_time.tzinfo is None:
                ref_time = ref_time.replace(tzinfo=timezone.utc)
            if ref_time > cutoff:
                continue

            # 确定 workspace 路径
            ws_path: Optional[Path] = None
            if s.workspace_path:
                ws_path = Path(s.workspace_path)
            else:
                # fallback：按约定路径 ~/.avatar/sessions/{session_id}
                ws_path = AVATAR_SESSIONS_DIR / s.id

            # 安全校验：只删 AVATAR_SESSIONS_DIR 下的目录
            try:
                ws_path.resolve().relative_to(AVATAR_SESSIONS_DIR.resolve())
            except ValueError:
                skipped.append(f"{s.id}: path {ws_path} outside sessions dir")
                continue

            if not ws_path.exists():
                continue  # 已经不存在，跳过

            try:
                shutil.rmtree(ws_path, ignore_errors=False)
                deleted_dirs.append(str(ws_path))
                logger.info(f"[ArtifactGC] Deleted session workspace: {ws_path}")
            except Exception as e:
                errors.append(f"{s.id}: {e}")
                logger.warning(f"[ArtifactGC] Failed to delete {ws_path}: {e}")

        # 清理 ArtifactRecord 中 storage_uri 文件已不存在的记录（标记，不删除）
        purged_records = self._purge_missing_artifact_records()

        return {
            "deleted_dirs": len(deleted_dirs),
            "deleted_paths": deleted_dirs,
            "skipped": skipped,
            "errors": errors,
            "purged_artifact_records": purged_records,
        }

    def _purge_missing_artifact_records(self) -> int:
        """
        扫描 ArtifactRecord，把 storage_uri 文件已不存在的记录的 storage_uri 标记为 'purged://'。
        不删除记录，保留血缘关系。
        """
        from app.db.artifact_record import ArtifactRecord

        count = 0
        with Session(engine) as db:
            records = db.exec(
                select(ArtifactRecord).where(
                    ~ArtifactRecord.storage_uri.startswith("purged://")
                )
            ).all()
            for r in records:
                if r.storage_uri.startswith("s3://"):
                    continue  # 远程存储跳过
                p = Path(r.storage_uri)
                if not p.exists():
                    r.storage_uri = f"purged://{r.storage_uri}"
                    db.add(r)
                    count += 1
            db.commit()

        if count:
            logger.info(f"[ArtifactGC] Marked {count} artifact records as purged")
        return count


# ---------------------------------------------------------------------------
# Session Archiver
# ---------------------------------------------------------------------------

class SessionArchiver:
    """
    把 completed/failed 且超过 archive_after_days 的 session 状态改为 archived。

    不删除 DB 记录，只改 status + archived_at。
    防止 DB 膨胀靠 purge 接口手动触发（未来可加）。
    """

    def __init__(self, archive_after_days: int = 30):
        self.archive_after_days = archive_after_days

    def run(self) -> dict:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.archive_after_days)
        archivable_statuses = {"completed", "failed", "cancelled"}

        archived_ids: list[str] = []

        with Session(engine) as db:
            sessions = db.exec(
                select(ExecutionSession).where(
                    ExecutionSession.status.in_(archivable_statuses)
                )
            ).all()

            now = datetime.now(timezone.utc)
            for s in sessions:
                ref_time = s.completed_at or s.created_at
                if ref_time is None:
                    continue
                if ref_time.tzinfo is None:
                    ref_time = ref_time.replace(tzinfo=timezone.utc)
                if ref_time > cutoff:
                    continue

                s.status = "archived"
                s.archived_at = now
                db.add(s)
                archived_ids.append(s.id)

            db.commit()

        if archived_ids:
            logger.info(f"[SessionArchiver] Archived {len(archived_ids)} sessions")

        return {
            "archived_count": len(archived_ids),
            "archived_ids": archived_ids,
        }


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

def run_gc(retention_days: int = 7) -> dict:
    return ArtifactGC(retention_days=retention_days).run()


def run_archiver(archive_after_days: int = 30) -> dict:
    return SessionArchiver(archive_after_days=archive_after_days).run()
