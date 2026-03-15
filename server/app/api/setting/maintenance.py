# app/api/maintenance.py
"""
Maintenance API — Artifact GC + Session Archiver

POST /maintenance/gc              — 触发 Artifact GC（清理过期 session workspace）
POST /maintenance/archive         — 触发 Session Archiver（归档旧 session）
POST /maintenance/gc-and-archive  — 一次性触发两者
GET  /maintenance/status          — 查看磁盘占用 + DB session 统计
"""
import logging
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/maintenance", tags=["maintenance"])


class GCRequest(BaseModel):
    retention_days: int = 7   # session workspace 保留天数


class ArchiveRequest(BaseModel):
    archive_after_days: int = 30  # session 归档阈值（天）


@router.post("/gc")
async def run_gc(body: GCRequest = GCRequest()):
    """
    清理过期 session workspace 目录（磁盘文件）。
    只清理 completed/failed/archived/cancelled 且超过 retention_days 的 session。
    """
    from app.services.gc_service import ArtifactGC
    result = ArtifactGC(retention_days=body.retention_days).run()
    logger.info(f"[MaintenanceAPI] GC completed: {result}")
    return {"success": True, **result}


@router.post("/archive")
async def run_archive(body: ArchiveRequest = ArchiveRequest()):
    """
    把 completed/failed 且超过 archive_after_days 的 session 状态改为 archived。
    不删除 DB 记录。
    """
    from app.services.gc_service import SessionArchiver
    result = SessionArchiver(archive_after_days=body.archive_after_days).run()
    logger.info(f"[MaintenanceAPI] Archive completed: {result}")
    return {"success": True, **result}


@router.post("/gc-and-archive")
async def run_gc_and_archive(
    retention_days: int = Query(7, ge=1),
    archive_after_days: int = Query(30, ge=1),
):
    """一次性触发 GC + Archive。"""
    from app.services.gc_service import ArtifactGC, SessionArchiver
    gc_result = ArtifactGC(retention_days=retention_days).run()
    archive_result = SessionArchiver(archive_after_days=archive_after_days).run()
    return {
        "success": True,
        "gc": gc_result,
        "archive": archive_result,
    }


@router.get("/status")
async def get_maintenance_status():
    """
    查看系统维护状态：
    - 磁盘：sessions 目录总大小、session workspace 数量
    - DB：各 status 的 session 数量统计
    """
    import os
    from pathlib import Path
    from sqlmodel import Session, select, func
    from app.db.database import engine
    from app.db.system import ExecutionSession
    from app.core.config import AVATAR_SESSIONS_DIR

    # 磁盘统计
    disk_info: dict = {"sessions_dir": str(AVATAR_SESSIONS_DIR), "total_size_mb": 0.0, "workspace_count": 0}
    try:
        total_bytes = 0
        workspace_count = 0
        if AVATAR_SESSIONS_DIR.exists():
            for entry in AVATAR_SESSIONS_DIR.iterdir():
                if entry.is_dir():
                    workspace_count += 1
                    for root, _, files in os.walk(entry):
                        for f in files:
                            try:
                                total_bytes += os.path.getsize(os.path.join(root, f))
                            except OSError:
                                pass
        disk_info["total_size_mb"] = round(total_bytes / 1024 / 1024, 2)
        disk_info["workspace_count"] = workspace_count
    except Exception as e:
        disk_info["error"] = str(e)

    # DB 统计
    db_info: dict = {}
    try:
        with Session(engine) as db:
            rows = db.exec(
                select(ExecutionSession.status, func.count(ExecutionSession.id).label("cnt"))
                .group_by(ExecutionSession.status)
            ).all()
            db_info = {row[0]: row[1] for row in rows}
    except Exception as e:
        db_info["error"] = str(e)

    return {
        "disk": disk_info,
        "db_sessions_by_status": db_info,
    }


# ---------------------------------------------------------------------------
# P3: Health check endpoint — module initialization status
# ---------------------------------------------------------------------------

@router.get("/health")
async def get_health():
    """
    P3: 返回各模块初始化状态和关键依赖可用性。
    检查：ArtifactRegistry / StepTraceStore / PolicyEngine / BudgetAccount
    """
    modules: dict = {}

    # ArtifactRegistry
    try:
        from app.avatar.runtime.artifact.registry import ArtifactRegistry
        ArtifactRegistry()
        modules["artifact_registry"] = {"status": "ok"}
    except Exception as e:
        modules["artifact_registry"] = {"status": "error", "detail": str(e)}

    # StepTraceStore
    try:
        from app.avatar.runtime.graph.storage.step_trace_store import StepTraceStore
        StepTraceStore()
        modules["step_trace_store"] = {"status": "ok"}
    except Exception as e:
        modules["step_trace_store"] = {"status": "error", "detail": str(e)}

    # PolicyEngine
    try:
        from app.avatar.runtime.policy.policy_engine import PolicyEngine
        PolicyEngine()
        modules["policy_engine"] = {"status": "ok"}
    except Exception as e:
        modules["policy_engine"] = {"status": "error", "detail": str(e)}

    # BudgetAccount
    try:
        from app.avatar.runtime.policy.budget_account import BudgetAccount
        BudgetAccount()
        modules["budget_account"] = {"status": "ok"}
    except Exception as e:
        modules["budget_account"] = {"status": "error", "detail": str(e)}

    # Database connectivity
    try:
        from app.db.database import engine
        from sqlmodel import Session, text
        with Session(engine) as db:
            db.exec(text("SELECT 1"))
        modules["database"] = {"status": "ok"}
    except Exception as e:
        modules["database"] = {"status": "error", "detail": str(e)}

    all_ok = all(m.get("status") == "ok" for m in modules.values())
    return {
        "status": "healthy" if all_ok else "degraded",
        "modules": modules,
    }
