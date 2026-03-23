"""
Task Ops API — 管理员运维端点

运维操作：
  POST /api/durable/ops/tasks/{id}/force-fail     强制标记任务失败
  POST /api/durable/ops/tasks/{id}/force-cancel    强制取消任务
  POST /api/durable/ops/tasks/{id}/skip-checkpoint 跳过 Checkpoint 恢复
  POST /api/durable/ops/approvals/{id}/redeliver   重新投递审批

所有运维操作写入 AuditLog。
"""
from fastapi import APIRouter, HTTPException
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/durable/ops")


def _write_audit_log(event_type: str, resource: str, operation: str, outcome: str = "success", details: dict = None):
    """写入审计日志。"""
    try:
        from sqlmodel import Session
        from app.db.database import engine
        from app.db.system import AuditLog

        log = AuditLog(
            event_type=event_type,
            actor="admin",
            resource=resource,
            operation=operation,
            outcome=outcome,
            details=details,
        )
        with Session(engine) as db:
            db.add(log)
            db.commit()
    except Exception as e:
        logger.warning(f"[OpsAPI] Audit log write failed: {e}")


@router.post("/tasks/{task_id}/force-fail")
def force_fail_task(task_id: str):
    """强制标记任务为 failed。"""
    from app.services.task_session_store import TaskSessionStore

    task = TaskSessionStore.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        TaskSessionStore.transition(
            task_id, "failed",
            last_transition_reason="admin_force_fail",
        )
    except Exception as e:
        _write_audit_log("ops.force_fail", task_id, "force_fail", "failed", {"error": str(e)})
        raise HTTPException(status_code=400, detail=str(e))

    _write_audit_log("ops.force_fail", task_id, "force_fail", "success")
    return {"task_id": task_id, "status": "failed"}


@router.post("/tasks/{task_id}/force-cancel")
def force_cancel_task(task_id: str):
    """强制取消任务。"""
    from app.services.task_session_store import TaskSessionStore

    task = TaskSessionStore.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        TaskSessionStore.transition(
            task_id, "cancelled",
            last_transition_reason="admin_force_cancel",
        )
    except Exception as e:
        _write_audit_log("ops.force_cancel", task_id, "force_cancel", "failed", {"error": str(e)})
        raise HTTPException(status_code=400, detail=str(e))

    _write_audit_log("ops.force_cancel", task_id, "force_cancel", "success")
    return {"task_id": task_id, "status": "cancelled"}


@router.post("/tasks/{task_id}/skip-checkpoint")
async def skip_checkpoint_recover(task_id: str):
    """跳过 Checkpoint 直接恢复（危险操作）。"""
    from app.services.task_session_store import TaskSessionStore

    task = TaskSessionStore.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        TaskSessionStore.transition(
            task_id, "executing",
            last_transition_reason="admin_skip_checkpoint_recover",
        )
    except Exception as e:
        _write_audit_log("ops.skip_checkpoint", task_id, "skip_checkpoint", "failed", {"error": str(e)})
        raise HTTPException(status_code=400, detail=str(e))

    _write_audit_log("ops.skip_checkpoint", task_id, "skip_checkpoint", "success")
    return {"task_id": task_id, "status": "executing", "warning": "Checkpoint skipped"}


@router.post("/approvals/{request_id}/redeliver")
def redeliver_approval(request_id: str):
    """重新投递审批请求。"""
    from app.services.approval_service import get_approval_service

    service = get_approval_service()
    if not hasattr(service, 'reopen_approval'):
        raise HTTPException(status_code=501, detail="Reopen not supported")

    result = service.reopen_approval(request_id)
    if not result:
        _write_audit_log("ops.redeliver_approval", request_id, "redeliver", "failed")
        raise HTTPException(status_code=404, detail="Approval request not found")

    _write_audit_log("ops.redeliver_approval", request_id, "redeliver", "success")
    return result
