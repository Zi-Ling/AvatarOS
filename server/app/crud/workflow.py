"""
Workflow CRUD Operations

提供工作流相关的数据库操作
"""
from typing import List, Optional
from sqlmodel import Session, select
import time

from app.db.workflow import WorkflowTemplateDB, WorkflowRunDB, WorkflowStageRunDB


# ========== WorkflowTemplate CRUD ==========

def create_workflow_template(
    db: Session,
    template_id: str,
    name: str,
    template_data: dict,
    description: str = "",
    schedule: Optional[str] = None,
    enabled: bool = True,
    category: str = "general",
    tags: List[str] = None,
    version: str = "1.0",
    author: Optional[str] = None
) -> WorkflowTemplateDB:
    """创建工作流模板"""
    now = time.time()
    
    db_template = WorkflowTemplateDB(
        id=template_id,
        name=name,
        description=description,
        template_data=template_data,
        schedule=schedule,
        enabled=enabled,
        category=category,
        tags=tags or [],
        version=version,
        author=author,
        created_at=now,
        updated_at=now
    )
    
    db.add(db_template)
    db.commit()
    db.refresh(db_template)
    
    return db_template


def get_workflow_template(db: Session, template_id: str) -> Optional[WorkflowTemplateDB]:
    """获取工作流模板"""
    statement = select(WorkflowTemplateDB).where(WorkflowTemplateDB.id == template_id)
    return db.exec(statement).first()


def list_workflow_templates(
    db: Session,
    category: Optional[str] = None,
    enabled: Optional[bool] = None,
    skip: int = 0,
    limit: int = 100
) -> List[WorkflowTemplateDB]:
    """列出工作流模板"""
    statement = select(WorkflowTemplateDB)
    
    if category:
        statement = statement.where(WorkflowTemplateDB.category == category)
    
    if enabled is not None:
        statement = statement.where(WorkflowTemplateDB.enabled == enabled)
    
    statement = statement.order_by(WorkflowTemplateDB.created_at.desc()).offset(skip).limit(limit)
    return list(db.exec(statement).all())


def update_workflow_template(
    db: Session,
    template_id: str,
    **updates
) -> Optional[WorkflowTemplateDB]:
    """更新工作流模板"""
    db_template = get_workflow_template(db, template_id)
    if not db_template:
        return None
    
    for key, value in updates.items():
        if hasattr(db_template, key):
            setattr(db_template, key, value)
    
    db_template.updated_at = time.time()
    
    db.commit()
    db.refresh(db_template)
    
    return db_template


def delete_workflow_template(db: Session, template_id: str) -> bool:
    """删除工作流模板"""
    db_template = get_workflow_template(db, template_id)
    if not db_template:
        return False
    
    db.delete(db_template)
    db.commit()
    
    return True


# ========== WorkflowRun CRUD ==========

def create_workflow_run(
    db: Session,
    run_id: str,
    workflow_id: str,
    workflow_name: str,
    status: str = "pending",
    inputs: dict = None,
    trigger_type: str = "manual"
) -> WorkflowRunDB:
    """创建工作流运行记录"""
    db_run = WorkflowRunDB(
        id=run_id,
        workflow_id=workflow_id,
        workflow_name=workflow_name,
        status=status,
        inputs=inputs or {},
        trigger_type=trigger_type
    )
    
    db.add(db_run)
    db.commit()
    db.refresh(db_run)
    
    return db_run


def get_workflow_run(db: Session, run_id: str) -> Optional[WorkflowRunDB]:
    """获取工作流运行记录"""
    statement = select(WorkflowRunDB).where(WorkflowRunDB.id == run_id)
    return db.exec(statement).first()


def list_workflow_runs(
    db: Session,
    workflow_id: Optional[str] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100
) -> List[WorkflowRunDB]:
    """列出工作流运行记录"""
    statement = select(WorkflowRunDB)
    
    if workflow_id:
        statement = statement.where(WorkflowRunDB.workflow_id == workflow_id)
    
    if status:
        statement = statement.where(WorkflowRunDB.status == status)
    
    statement = statement.order_by(WorkflowRunDB.start_time.desc()).offset(skip).limit(limit)
    return list(db.exec(statement).all())


def update_workflow_run(
    db: Session,
    run_id: str,
    **updates
) -> Optional[WorkflowRunDB]:
    """更新工作流运行记录"""
    db_run = get_workflow_run(db, run_id)
    if not db_run:
        return None
    
    for key, value in updates.items():
        if hasattr(db_run, key):
            setattr(db_run, key, value)
    
    db.commit()
    db.refresh(db_run)
    
    return db_run


# ========== WorkflowStageRun CRUD ==========

def create_workflow_stage_run(
    db: Session,
    workflow_run_id: str,
    stage_id: str,
    stage_name: str,
    status: str = "pending"
) -> WorkflowStageRunDB:
    """创建阶段运行记录"""
    db_stage_run = WorkflowStageRunDB(
        workflow_run_id=workflow_run_id,
        stage_id=stage_id,
        stage_name=stage_name,
        status=status
    )
    
    db.add(db_stage_run)
    db.commit()
    db.refresh(db_stage_run)
    
    return db_stage_run


def get_workflow_stage_runs(db: Session, workflow_run_id: str) -> List[WorkflowStageRunDB]:
    """获取某个工作流运行的所有阶段记录"""
    statement = select(WorkflowStageRunDB).where(
        WorkflowStageRunDB.workflow_run_id == workflow_run_id
    )
    return list(db.exec(statement).all())


def update_workflow_stage_run(
    db: Session,
    stage_run_id: int,
    **updates
) -> Optional[WorkflowStageRunDB]:
    """更新阶段运行记录"""
    statement = select(WorkflowStageRunDB).where(
        WorkflowStageRunDB.id == stage_run_id
    )
    db_stage_run = db.exec(statement).first()
    
    if not db_stage_run:
        return None
    
    for key, value in updates.items():
        if hasattr(db_stage_run, key):
            setattr(db_stage_run, key, value)
    
    db.commit()
    db.refresh(db_stage_run)
    
    return db_stage_run

