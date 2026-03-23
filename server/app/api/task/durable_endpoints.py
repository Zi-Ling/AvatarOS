"""
Durable Task State Machine API — 持久化任务状态机端点

端点：
  GET  /api/durable/tasks/active          获取所有活跃任务
  GET  /api/durable/tasks/{id}/checkpoints 获取任务 Checkpoint 列表
  GET  /api/durable/tasks/{id}/effects     获取任务 Effect Ledger
  POST /api/durable/tasks/{id}/recover     手动触发恢复
  POST /api/durable/approvals/{id}/reopen  重新发起审批
  GET  /api/durable/tasks/{id}/events      补齐缺失事件（断档回源）
"""
from fastapi import APIRouter, HTTPException
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/durable")


@router.get("/tasks/active")
def get_active_tasks():
    """获取所有活跃任务（executing/paused/waiting_approval）。"""
    from app.services.task_session_store import TaskSessionStore

    tasks = TaskSessionStore.get_active_tasks()
    return [
        {
            "id": t.id,
            "goal": t.goal,
            "status": t.status,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            "worker_id": t.worker_id,
        }
        for t in tasks
    ]


@router.get("/tasks/{task_id}/checkpoints")
def get_task_checkpoints(task_id: str):
    """获取任务 Checkpoint 列表。"""
    from app.services.checkpoint_store import CheckpointStore

    checkpoints = CheckpointStore.get_by_task_session(task_id)
    if not checkpoints:
        return []

    return [
        {
            "id": cp.id,
            "importance": cp.importance,
            "reason": cp.reason,
            "graph_version": cp.graph_version,
            "checksum": cp.checksum,
            "created_at": cp.created_at.isoformat() if cp.created_at else None,
            "has_frontier": cp.execution_frontier_json is not None,
            "has_effects": cp.effect_ledger_snapshot_json is not None,
        }
        for cp in checkpoints
    ]


@router.get("/tasks/{task_id}/effects")
def get_task_effects(task_id: str):
    """获取任务 Effect Ledger。"""
    from app.services.effect_ledger_store import EffectLedgerStore

    effects = EffectLedgerStore.get_by_task(task_id)
    return [
        {
            "id": e.id,
            "step_id": e.step_id,
            "effect_type": e.effect_type,
            "status": e.status,
            "target_path": e.target_path,
            "content_hash": e.content_hash,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in effects
    ]


@router.post("/tasks/{task_id}/recover")
async def recover_task(task_id: str):
    """手动触发任务恢复。"""
    from app.services.task_session_store import TaskSessionStore
    from app.services.recovery_engine import RecoveryEngine

    task = TaskSessionStore.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    engine = RecoveryEngine()
    success = await engine.recover_task(task)
    return {
        "task_id": task_id,
        "recovered": success,
        "status": task.status,
    }


@router.post("/approvals/{request_id}/reopen")
def reopen_approval(request_id: str):
    """重新发起审批（超时后重发）。"""
    from app.services.approval_service import get_approval_service

    service = get_approval_service()
    if not hasattr(service, 'reopen_approval'):
        raise HTTPException(status_code=501, detail="Reopen not supported")

    result = service.reopen_approval(request_id)
    if not result:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return result


@router.get("/tasks/{task_id}/events")
def get_task_events(task_id: str, after_sequence: int = 0):
    """补齐缺失事件（断档回源）。"""
    from app.services.task_session_store import TaskSessionStore

    task = TaskSessionStore.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return {
        "task_id": task_id,
        "last_sequence": task.last_event_sequence if hasattr(task, 'last_event_sequence') else 0,
        "events": [],  # TODO: 从持久化事件存储中查询 after_sequence 之后的事件
    }
