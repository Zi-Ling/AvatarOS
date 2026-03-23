"""
工作流实例管理 API。

端点：
- POST   /workflows/instances              创建并执行
- GET    /workflows/instances              列表
- GET    /workflows/instances/{id}         详情（含 step runs）
- POST   /workflows/instances/{id}/pause   暂停
- POST   /workflows/instances/{id}/resume  恢复
- POST   /workflows/instances/{id}/cancel  取消
- POST   /workflows/instances/{id}/retry   重试
- POST   /workflows/instances/{id}/rerun   重新执行
"""
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db.database import engine
from app.services.workflow.models import (
    WorkflowInstance,
    WorkflowStepRun,
)

router = APIRouter(prefix="/workflows/instances", tags=["workflow-instances"])


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------

class CreateInstanceRequest(BaseModel):
    template_version_id: str
    params: dict[str, Any] = {}
    trigger_id: Optional[str] = None


# ---------------------------------------------------------------------------
# 依赖注入辅助
# ---------------------------------------------------------------------------

_instance_manager = None


def set_instance_manager(mgr):
    global _instance_manager
    _instance_manager = mgr


def _get_mgr():
    if not _instance_manager:
        raise HTTPException(status_code=503, detail="Instance manager not initialized")
    return _instance_manager


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------

@router.post("/")
async def create_instance(body: CreateInstanceRequest):
    """创建并执行工作流实例。"""
    mgr = _get_mgr()
    try:
        inst = await mgr.create_and_run(
            template_version_id=body.template_version_id,
            params=body.params,
            trigger_id=body.trigger_id,
        )
        return {
            "id": inst.id,
            "template_version_id": inst.template_version_id,
            "status": inst.status,
            "execution_context_id": inst.execution_context_id,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/")
async def list_instances(
    template_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=50, le=200),
):
    """列表，支持过滤。返回含模板名称和步骤进度的摘要。"""
    from app.services.workflow.models import WorkflowTemplate

    with Session(engine) as db:
        stmt = select(WorkflowInstance).where(WorkflowInstance.is_deleted == False)
        if template_id:
            stmt = stmt.where(WorkflowInstance.template_id == template_id)
        if status:
            stmt = stmt.where(WorkflowInstance.status == status)
        stmt = stmt.order_by(WorkflowInstance.created_at.desc()).limit(limit)
        instances = db.exec(stmt).all()

        # 批量获取模板名称
        tpl_ids = list({i.template_id for i in instances})
        tpl_map: dict[str, str] = {}
        if tpl_ids:
            templates = db.exec(
                select(WorkflowTemplate).where(WorkflowTemplate.id.in_(tpl_ids))
            ).all()
            tpl_map = {t.id: t.name for t in templates}

        # 批量获取 step runs
        inst_ids = [i.id for i in instances]
        step_runs_map: dict[str, list] = {iid: [] for iid in inst_ids}
        if inst_ids:
            all_step_runs = db.exec(
                select(WorkflowStepRun).where(WorkflowStepRun.instance_id.in_(inst_ids))
            ).all()
            for sr in all_step_runs:
                step_runs_map[sr.instance_id].append(sr)

    result = []
    for i in instances:
        # 计算 duration
        duration = None
        if i.started_at and i.completed_at:
            duration = (i.completed_at - i.started_at).total_seconds()

        step_runs = step_runs_map.get(i.id, [])
        result.append({
            "id": i.id,
            "template_id": i.template_id,
            "template_version_id": i.template_version_id,
            "workflow_name": tpl_map.get(i.template_id, "Unknown"),
            "status": i.status,
            "start_time": i.started_at.timestamp() if i.started_at else None,
            "end_time": i.completed_at.timestamp() if i.completed_at else None,
            "duration": duration,
            "created_at": i.created_at.isoformat() if i.created_at else None,
            "error": i.outputs.get("error") if i.outputs else None,
            "step_runs": [
                {
                    "step_id": sr.step_id,
                    "step_name": sr.step_id,
                    "status": sr.status,
                    "duration": sr.duration_ms / 1000.0 if sr.duration_ms else None,
                    "error": sr.error,
                }
                for sr in step_runs
            ],
        })
    return result


@router.get("/{instance_id}")
async def get_instance(instance_id: str):
    """获取实例详情 + 所有 step runs。"""
    with Session(engine) as db:
        inst = db.get(WorkflowInstance, instance_id)
        if not inst:
            raise HTTPException(status_code=404, detail="Instance not found")
        step_runs = db.exec(
            select(WorkflowStepRun).where(
                WorkflowStepRun.instance_id == instance_id
            )
        ).all()

    return {
        "id": inst.id,
        "template_id": inst.template_id,
        "template_version_id": inst.template_version_id,
        "execution_context_id": inst.execution_context_id,
        "status": inst.status,
        "params": inst.params,
        "outputs": inst.outputs,
        "created_at": inst.created_at.isoformat() if inst.created_at else None,
        "started_at": inst.started_at.isoformat() if inst.started_at else None,
        "completed_at": inst.completed_at.isoformat() if inst.completed_at else None,
        "step_runs": [
            {
                "id": sr.id, "step_id": sr.step_id, "status": sr.status,
                "executor_type": sr.executor_type,
                "inputs": sr.inputs, "outputs": sr.outputs,
                "error": sr.error, "retry_count": sr.retry_count,
                "duration_ms": sr.duration_ms,
            }
            for sr in step_runs
        ],
    }


@router.post("/{instance_id}/pause")
async def pause_instance(instance_id: str):
    mgr = _get_mgr()
    try:
        await mgr.pause(instance_id)
        return {"message": "Instance pausing"}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{instance_id}/resume")
async def resume_instance(instance_id: str):
    mgr = _get_mgr()
    try:
        await mgr.resume(instance_id)
        return {"message": "Instance resumed"}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{instance_id}/cancel")
async def cancel_instance(instance_id: str):
    mgr = _get_mgr()
    try:
        await mgr.cancel(instance_id)
        return {"message": "Instance cancelled"}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{instance_id}/retry")
async def retry_instance(instance_id: str):
    mgr = _get_mgr()
    try:
        await mgr.retry(instance_id)
        return {"message": "Instance retrying"}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{instance_id}/rerun")
async def rerun_instance(instance_id: str):
    mgr = _get_mgr()
    try:
        new_inst = await mgr.rerun(instance_id)
        return {"id": new_inst.id, "status": new_inst.status}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
