"""
Workflow API Router

提供工作流相关的API接口：
- 模板管理（CRUD）
- 工作流执行
- 执行历史查询
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlmodel import Session

from app.db.database import get_db
from app.crud import workflow as workflow_crud
import time
import uuid

router = APIRouter(prefix="/api/workflow", tags=["workflow"])


# ========== Request/Response Models ==========

class WorkflowTemplateCreate(BaseModel):
    """创建工作流模板的请求"""
    name: str
    description: str = ""
    template_data: dict
    schedule: Optional[str] = None
    enabled: bool = True
    category: str = "general"
    tags: List[str] = []


class WorkflowTemplateResponse(BaseModel):
    """工作流模板响应"""
    id: str
    name: str
    description: str
    schedule: Optional[str]
    enabled: bool
    category: str
    tags: List[str]
    created_at: float
    updated_at: float


class WorkflowExecuteRequest(BaseModel):
    """执行工作流的请求"""
    inputs: dict = {}


class WorkflowRunResponse(BaseModel):
    """工作流执行响应"""
    id: str
    workflow_id: str
    workflow_name: str
    status: str
    start_time: Optional[float]
    end_time: Optional[float]
    duration: Optional[float]
    error: Optional[str]


# ========== Template Management Endpoints ==========

@router.post("/templates", response_model=WorkflowTemplateResponse)
async def create_workflow_template(
    request: WorkflowTemplateCreate,
    db: Session = Depends(get_db)
):
    """创建工作流模板"""
    template_id = str(uuid.uuid4())
    
    db_template = workflow_crud.create_workflow_template(
        db=db,
        template_id=template_id,
        name=request.name,
        description=request.description,
        template_data=request.template_data,
        schedule=request.schedule,
        enabled=request.enabled,
        category=request.category,
        tags=request.tags
    )
    
    return WorkflowTemplateResponse(
        id=db_template.id,
        name=db_template.name,
        description=db_template.description,
        schedule=db_template.schedule,
        enabled=db_template.enabled,
        category=db_template.category,
        tags=db_template.tags,
        created_at=db_template.created_at,
        updated_at=db_template.updated_at
    )


@router.get("/templates", response_model=List[WorkflowTemplateResponse])
async def list_workflow_templates(
    category: Optional[str] = None,
    enabled: Optional[bool] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """列出所有工作流模板"""
    templates = workflow_crud.list_workflow_templates(
        db=db,
        category=category,
        enabled=enabled,
        skip=skip,
        limit=limit
    )
    
    return [
        WorkflowTemplateResponse(
            id=t.id,
            name=t.name,
            description=t.description,
            schedule=t.schedule,
            enabled=t.enabled,
            category=t.category,
            tags=t.tags,
            created_at=t.created_at,
            updated_at=t.updated_at
        )
        for t in templates
    ]


@router.get("/templates/{template_id}")
async def get_workflow_template(
    template_id: str,
    db: Session = Depends(get_db)
):
    """获取工作流模板详情"""
    template = workflow_crud.get_workflow_template(db, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "template_data": template.template_data,
        "schedule": template.schedule,
        "enabled": template.enabled,
        "category": template.category,
        "tags": template.tags,
        "created_at": template.created_at,
        "updated_at": template.updated_at
    }


@router.put("/templates/{template_id}")
async def update_workflow_template(
    template_id: str,
    updates: dict,
    db: Session = Depends(get_db)
):
    """更新工作流模板"""
    template = workflow_crud.update_workflow_template(db, template_id, **updates)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    return {"message": "Template updated successfully"}


@router.delete("/templates/{template_id}")
async def delete_workflow_template(
    template_id: str,
    db: Session = Depends(get_db)
):
    """删除工作流模板"""
    success = workflow_crud.delete_workflow_template(db, template_id)
    if not success:
        raise HTTPException(status_code=404, detail="Template not found")
    
    return {"message": "Template deleted successfully"}


# ========== Workflow Execution Endpoints ==========

@router.post("/templates/{template_id}/execute", response_model=WorkflowRunResponse)
async def execute_workflow(
    template_id: str,
    request: WorkflowExecuteRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """执行工作流（后台执行）"""
    # 获取模板
    db_template = workflow_crud.get_workflow_template(db, template_id)
    if not db_template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    # 创建运行记录
    run_id = str(uuid.uuid4())
    db_run = workflow_crud.create_workflow_run(
        db=db,
        run_id=run_id,
        workflow_id=template_id,
        workflow_name=db_template.name,
        status="pending",
        inputs=request.inputs,
        trigger_type="manual"
    )
    
    # 后台执行工作流
    # TODO: 实际执行需要通过 WorkflowEngine
    # background_tasks.add_task(execute_workflow_task, template_id, run_id, request.inputs)
    
    return WorkflowRunResponse(
        id=db_run.id,
        workflow_id=db_run.workflow_id,
        workflow_name=db_run.workflow_name,
        status=db_run.status,
        start_time=db_run.start_time,
        end_time=db_run.end_time,
        duration=None,
        error=db_run.error
    )


@router.get("/runs", response_model=List[WorkflowRunResponse])
async def list_workflow_runs(
    workflow_id: Optional[str] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """列出工作流执行记录"""
    runs = workflow_crud.list_workflow_runs(
        db=db,
        workflow_id=workflow_id,
        status=status,
        skip=skip,
        limit=limit
    )
    
    return [
        WorkflowRunResponse(
            id=r.id,
            workflow_id=r.workflow_id,
            workflow_name=r.workflow_name,
            status=r.status,
            start_time=r.start_time,
            end_time=r.end_time,
            duration=(r.end_time - r.start_time) if r.start_time and r.end_time else None,
            error=r.error
        )
        for r in runs
    ]


@router.get("/runs/{run_id}")
async def get_workflow_run_detail(
    run_id: str,
    db: Session = Depends(get_db)
):
    """获取工作流执行详情"""
    run = workflow_crud.get_workflow_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    
    # 获取阶段执行记录
    stage_runs = workflow_crud.get_workflow_stage_runs(db, run_id)
    
    return {
        "id": run.id,
        "workflow_id": run.workflow_id,
        "workflow_name": run.workflow_name,
        "status": run.status,
        "start_time": run.start_time,
        "end_time": run.end_time,
        "duration": (run.end_time - run.start_time) if run.start_time and run.end_time else None,
        "inputs": run.inputs,
        "error": run.error,
        "trigger_type": run.trigger_type,
        "stage_runs": [
            {
                "stage_id": sr.stage_id,
                "stage_name": sr.stage_name,
                "status": sr.status,
                "start_time": sr.start_time,
                "end_time": sr.end_time,
                "duration": (sr.end_time - sr.start_time) if sr.start_time and sr.end_time else None,
                "outputs": sr.outputs,
                "error": sr.error
            }
            for sr in stage_runs
        ]
    }






















