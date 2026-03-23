"""
工作流模板管理 API。

端点：
- POST   /workflows/templates          创建模板
- GET    /workflows/templates          列表
- GET    /workflows/templates/{id}     详情
- PUT    /workflows/templates/{id}     更新（自动创建新版本）
- DELETE /workflows/templates/{id}     软删除
- POST   /workflows/templates/{id}/clone  克隆
- GET    /workflows/templates/{id}/versions/{vid}  版本详情
"""
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.workflow.models import (
    StepFailurePolicy,
    WorkflowEdgeDef,
    WorkflowParamDef,
    WorkflowStepDef,
)

router = APIRouter(prefix="/workflows/templates", tags=["workflow-templates"])


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------

class CreateTemplateRequest(BaseModel):
    name: str
    description: str = ""
    tags: list[str] = []
    steps: list[WorkflowStepDef]
    edges: list[WorkflowEdgeDef] = []
    parameters: list[WorkflowParamDef] = []
    global_failure_policy: str = StepFailurePolicy.FAIL_FAST.value


class UpdateTemplateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    steps: Optional[list[WorkflowStepDef]] = None
    edges: Optional[list[WorkflowEdgeDef]] = None
    parameters: Optional[list[WorkflowParamDef]] = None
    global_failure_policy: Optional[str] = None


class CloneRequest(BaseModel):
    new_name: str


# ---------------------------------------------------------------------------
# 依赖注入辅助
# ---------------------------------------------------------------------------

def _get_store():
    from app.services.workflow.template_store import TemplateStore
    return TemplateStore()


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------

@router.post("/")
async def create_template(body: CreateTemplateRequest):
    """创建模板 + 第一个版本。"""
    store = _get_store()
    try:
        tpl = store.create_template(
            name=body.name,
            description=body.description,
            tags=body.tags,
            steps=[s.model_dump() for s in body.steps],
            edges=[e.model_dump() for e in body.edges],
            parameters=[p.model_dump() for p in body.parameters],
            global_failure_policy=body.global_failure_policy,
        )
        return {"id": tpl.id, "name": tpl.name, "latest_version_id": tpl.latest_version_id}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/")
async def list_templates(tags: Optional[list[str]] = Query(None)):
    """列表，支持 tags 过滤。"""
    store = _get_store()
    templates = store.list_templates(tags=tags)
    return [
        {
            "id": t.id, "name": t.name, "description": t.description,
            "tags": t.tags, "latest_version_id": t.latest_version_id,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in templates
    ]


@router.get("/{template_id}")
async def get_template(template_id: str):
    """获取模板详情。"""
    store = _get_store()
    tpl = store.get_template(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    versions = store.list_versions(template_id)
    return {
        "id": tpl.id, "name": tpl.name, "description": tpl.description,
        "tags": tpl.tags, "latest_version_id": tpl.latest_version_id,
        "versions": [
            {"id": v.id, "version_number": v.version_number, "created_at": v.created_at.isoformat() if v.created_at else None}
            for v in versions
        ],
    }


@router.get("/{template_id}/versions/{version_id}")
async def get_version(template_id: str, version_id: str):
    """获取特定版本详情。"""
    store = _get_store()
    v = store.get_version(version_id)
    if not v or v.template_id != template_id:
        raise HTTPException(status_code=404, detail="Version not found")
    return {
        "id": v.id, "template_id": v.template_id,
        "version_number": v.version_number,
        "steps": v.steps, "edges": v.edges, "parameters": v.parameters,
        "global_failure_policy": v.global_failure_policy,
        "content_hash": v.content_hash,
    }


@router.put("/{template_id}")
async def update_template(template_id: str, body: UpdateTemplateRequest):
    """更新模板（自动创建新版本）。"""
    store = _get_store()
    kwargs: dict[str, Any] = {}
    if body.name is not None:
        kwargs["name"] = body.name
    if body.description is not None:
        kwargs["description"] = body.description
    if body.tags is not None:
        kwargs["tags"] = body.tags
    if body.steps is not None:
        kwargs["steps"] = [s.model_dump() for s in body.steps]
    if body.edges is not None:
        kwargs["edges"] = [e.model_dump() for e in body.edges]
    if body.parameters is not None:
        kwargs["parameters"] = [p.model_dump() for p in body.parameters]
    if body.global_failure_policy is not None:
        kwargs["global_failure_policy"] = body.global_failure_policy

    try:
        version = store.update_template(template_id, **kwargs)
        return {"version_id": version.id, "version_number": version.version_number}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/{template_id}")
async def delete_template(template_id: str):
    """软删除模板。"""
    store = _get_store()
    try:
        store.delete_template(template_id)
        return {"message": "Template deleted"}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{template_id}/clone")
async def clone_template(template_id: str, body: CloneRequest):
    """克隆模板。"""
    store = _get_store()
    try:
        tpl = store.clone_template(template_id, body.new_name)
        return {"id": tpl.id, "name": tpl.name}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
