# server/app/api/task_session.py
"""
长任务 API 端点 — 完整集成 TaskSessionManager

POST /task-sessions — 创建长任务
POST /task-sessions/{id}/pause — 暂停
POST /task-sessions/{id}/resume — 恢复
POST /task-sessions/{id}/cancel — 取消
POST /task-sessions/{id}/change — 提交变更请求
GET  /task-sessions/{id} — 查询状态
GET  /task-sessions/{id}/checkpoints — 查询检查点列表
GET  /task-sessions/{id}/delivery — 获取交付包
GET  /task-sessions/{id}/events — 查询事件流
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.task_session_store import TaskSessionStore
from app.services.checkpoint_store import CheckpointStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/task-sessions", tags=["task-sessions"])

# Module-level references — set during app startup via set_managers()
_task_session_manager = None
_event_streams: dict[str, object] = {}  # task_session_id → TaskEventStream


def set_task_session_manager(manager) -> None:
    """Inject TaskSessionManager instance (called during bootstrap)."""
    global _task_session_manager
    _task_session_manager = manager


def register_event_stream(task_session_id: str, stream) -> None:
    """Register a TaskEventStream for API queries."""
    _event_streams[task_session_id] = stream


def unregister_event_stream(task_session_id: str) -> None:
    _event_streams.pop(task_session_id, None)


class CreateTaskSessionRequest(BaseModel):
    goal: str
    config: dict | None = None


class ChangeRequest(BaseModel):
    raw_input: str


def _require_manager():
    if _task_session_manager is None:
        raise HTTPException(
            status_code=503,
            detail="TaskSessionManager not initialized",
        )
    return _task_session_manager


# ------------------------------------------------------------------
# POST endpoints
# ------------------------------------------------------------------

@router.post("")
async def create_task_session(req: CreateTaskSessionRequest):
    """POST /task-sessions — 创建长任务"""
    mgr = _require_manager()
    session = await mgr.create_task_session(goal=req.goal, config=req.config)
    logger.info(f"[TaskSessionAPI] Created task session {session.id}")
    return {
        "id": session.id,
        "goal": session.goal,
        "status": session.status,
        "created_at": session.created_at.isoformat(),
    }


@router.post("/{task_session_id}/pause")
async def pause_task_session(task_session_id: str):
    """POST /task-sessions/{id}/pause — 暂停"""
    mgr = _require_manager()
    session = TaskSessionStore.get(task_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="TaskSession not found")
    try:
        await mgr.handle_pause(task_session_id)
    except Exception as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"task_session_id": task_session_id, "action": "pause", "status": "paused"}


@router.post("/{task_session_id}/resume")
async def resume_task_session(task_session_id: str):
    """POST /task-sessions/{id}/resume — 恢复"""
    mgr = _require_manager()
    session = TaskSessionStore.get(task_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="TaskSession not found")
    try:
        await mgr.handle_resume(task_session_id)
    except Exception as e:
        raise HTTPException(status_code=409, detail=str(e))
    updated = TaskSessionStore.get(task_session_id)
    return {
        "task_session_id": task_session_id,
        "action": "resume",
        "status": updated.status if updated else "unknown",
    }


@router.post("/{task_session_id}/cancel")
async def cancel_task_session(task_session_id: str):
    """POST /task-sessions/{id}/cancel — 取消"""
    mgr = _require_manager()
    session = TaskSessionStore.get(task_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="TaskSession not found")
    try:
        await mgr.handle_cancel(task_session_id)
    except Exception as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"task_session_id": task_session_id, "action": "cancel", "status": "cancelled"}


@router.post("/{task_session_id}/change")
async def submit_change_request(task_session_id: str, req: ChangeRequest):
    """POST /task-sessions/{id}/change — 提交变更请求"""
    mgr = _require_manager()
    session = TaskSessionStore.get(task_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="TaskSession not found")
    try:
        result = await mgr.handle_change_request(task_session_id, req.raw_input)
    except Exception as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {
        "task_session_id": task_session_id,
        "action": "change",
        **result,
    }


# ------------------------------------------------------------------
# GET endpoints
# ------------------------------------------------------------------

@router.get("/{task_session_id}")
async def get_task_session(task_session_id: str):
    """GET /task-sessions/{id} — 查询状态"""
    session = TaskSessionStore.get(task_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="TaskSession not found")
    return {
        "id": session.id,
        "goal": session.goal,
        "status": session.status,
        "current_graph_id": session.current_graph_id,
        "current_graph_version": session.current_graph_version,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
    }


@router.get("/{task_session_id}/checkpoints")
async def get_checkpoints(task_session_id: str):
    """GET /task-sessions/{id}/checkpoints — 查询检查点列表"""
    session = TaskSessionStore.get(task_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="TaskSession not found")
    checkpoints = CheckpointStore.get_by_task_session(task_session_id)
    return [
        {
            "id": cp.id,
            "importance": cp.importance,
            "reason": cp.reason,
            "graph_version": cp.graph_version,
            "created_at": cp.created_at.isoformat(),
        }
        for cp in checkpoints
    ]


@router.get("/{task_session_id}/delivery")
async def get_delivery(task_session_id: str):
    """GET /task-sessions/{id}/delivery — 获取交付包"""
    mgr = _require_manager()
    session = TaskSessionStore.get(task_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="TaskSession not found")
    try:
        result = await mgr.finalize(task_session_id)
    except Exception as e:
        raise HTTPException(status_code=409, detail=str(e))
    return result


@router.get("/{task_session_id}/events")
async def get_events(
    task_session_id: str,
    event_type: Optional[str] = None,
    limit: int = 100,
):
    """GET /task-sessions/{id}/events — 查询事件流（支持分页和事件类型过滤）"""
    session = TaskSessionStore.get(task_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="TaskSession not found")

    stream = _event_streams.get(task_session_id)
    if stream is None:
        return {
            "task_session_id": task_session_id,
            "event_type_filter": event_type,
            "limit": limit,
            "events": [],
        }

    events = stream.get_events(event_type=event_type, limit=limit)
    return {
        "task_session_id": task_session_id,
        "event_type_filter": event_type,
        "limit": limit,
        "events": events,
    }
