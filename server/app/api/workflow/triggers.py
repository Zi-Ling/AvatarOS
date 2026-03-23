"""
工作流触发器管理 API。

端点：
- POST   /workflows/triggers          创建触发器
- GET    /workflows/triggers          列表
- PUT    /workflows/triggers/{id}     更新
- DELETE /workflows/triggers/{id}     删除
- POST   /workflows/triggers/{id}/fire  手动触发
"""
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.workflow.models import TriggerType, VersionMode

router = APIRouter(prefix="/workflows/triggers", tags=["workflow-triggers"])


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------

class CreateTriggerRequest(BaseModel):
    template_id: str
    trigger_type: str = TriggerType.MANUAL.value
    template_version_id: Optional[str] = None
    version_mode: str = VersionMode.FIXED.value
    cron_expression: Optional[str] = None
    source_workflow_template_id: Optional[str] = None
    default_params: dict[str, Any] = {}


class UpdateTriggerRequest(BaseModel):
    version_mode: Optional[str] = None
    template_version_id: Optional[str] = None
    cron_expression: Optional[str] = None
    default_params: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None


class FireTriggerRequest(BaseModel):
    extra_params: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# 依赖注入辅助
# ---------------------------------------------------------------------------

_trigger_manager = None


def set_trigger_manager(mgr):
    global _trigger_manager
    _trigger_manager = mgr


def _get_mgr():
    if not _trigger_manager:
        raise HTTPException(status_code=503, detail="Trigger manager not initialized")
    return _trigger_manager


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------

@router.post("/")
async def create_trigger(body: CreateTriggerRequest):
    mgr = _get_mgr()
    try:
        trigger = mgr.create_trigger(
            template_id=body.template_id,
            trigger_type=body.trigger_type,
            template_version_id=body.template_version_id,
            version_mode=body.version_mode,
            cron_expression=body.cron_expression,
            source_workflow_template_id=body.source_workflow_template_id,
            default_params=body.default_params,
        )
        return {
            "id": trigger.id, "template_id": trigger.template_id,
            "trigger_type": trigger.trigger_type,
            "version_mode": trigger.version_mode,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/")
async def list_triggers(template_id: Optional[str] = None):
    mgr = _get_mgr()
    triggers = mgr.list_triggers(template_id=template_id)
    return [
        {
            "id": t.id, "template_id": t.template_id,
            "trigger_type": t.trigger_type,
            "version_mode": t.version_mode,
            "is_active": t.is_active,
            "cron_expression": t.cron_expression,
        }
        for t in triggers
    ]


@router.put("/{trigger_id}")
async def update_trigger(trigger_id: str, body: UpdateTriggerRequest):
    mgr = _get_mgr()
    try:
        trigger = mgr.update_trigger(
            trigger_id=trigger_id,
            version_mode=body.version_mode,
            template_version_id=body.template_version_id,
            cron_expression=body.cron_expression,
            default_params=body.default_params,
            is_active=body.is_active,
        )
        return {"id": trigger.id, "version_mode": trigger.version_mode}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/{trigger_id}")
async def delete_trigger(trigger_id: str):
    mgr = _get_mgr()
    try:
        mgr.delete_trigger(trigger_id)
        return {"message": "Trigger deleted"}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{trigger_id}/fire")
async def fire_trigger(trigger_id: str, body: FireTriggerRequest):
    mgr = _get_mgr()
    try:
        inst = await mgr.fire_trigger(trigger_id, extra_params=body.extra_params)
        return {"instance_id": inst.id, "status": inst.status}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
