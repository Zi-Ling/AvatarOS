"""
Workflow Database Models

定义工作流相关的数据库表：
- workflow_templates: 工作流模板
- workflow_runs: 工作流执行记录
- workflow_stage_runs: 阶段执行记录
"""
from typing import Optional, List, Dict, Any
from sqlmodel import SQLModel, Field, Relationship, Column, JSON as SQLJSON
from sqlalchemy import Text


class WorkflowTemplateDB(SQLModel, table=True):
    """工作流模板表"""
    __tablename__ = "workflow_templates"
    
    id: str = Field(primary_key=True)
    name: str
    description: str = ""
    
    # 模板内容（JSON格式存储完整模板）
    template_data: Dict[str, Any] = Field(sa_column=Column(SQLJSON))
    
    # 调度配置
    schedule: Optional[str] = None  # Cron表达式
    enabled: bool = True
    
    # 分类和标签
    category: str = "general"
    tags: List[str] = Field(default=[], sa_column=Column(SQLJSON))
    
    # 版本和作者
    version: str = "1.0"
    author: Optional[str] = None
    
    # 时间戳
    created_at: float
    updated_at: float
    
    # 关联关系
    runs: List["WorkflowRunDB"] = Relationship(back_populates="template")


class WorkflowRunDB(SQLModel, table=True):
    """工作流执行记录表"""
    __tablename__ = "workflow_runs"
    
    id: str = Field(primary_key=True)
    workflow_id: str = Field(foreign_key="workflow_templates.id")
    workflow_name: str
    
    # 执行状态
    status: str  # pending, running, success, failed, cancelled
    
    # 时间记录
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    
    # 输入和上下文
    inputs: Dict[str, Any] = Field(default={}, sa_column=Column(SQLJSON))
    context: Dict[str, Any] = Field(default={}, sa_column=Column(SQLJSON))
    
    # 错误信息
    error: Optional[str] = Field(default=None, sa_column=Column(Text))
    retry_count: int = 0
    
    # 触发方式
    trigger_type: str = "manual"  # manual, scheduled, event
    
    # 关联关系
    template: Optional[WorkflowTemplateDB] = Relationship(back_populates="runs")
    stage_runs: List["WorkflowStageRunDB"] = Relationship(back_populates="workflow_run")


class WorkflowStageRunDB(SQLModel, table=True):
    """阶段执行记录表"""
    __tablename__ = "workflow_stage_runs"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    workflow_run_id: str = Field(foreign_key="workflow_runs.id")
    
    # 阶段信息
    stage_id: str
    stage_name: str
    
    # 执行状态
    status: str  # pending, running, success, failed, skipped
    
    # 时间记录
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    
    # 输入输出
    inputs: Dict[str, Any] = Field(default={}, sa_column=Column(SQLJSON))
    outputs: Dict[str, Any] = Field(default={}, sa_column=Column(SQLJSON))
    
    # 关联的Task
    task_id: Optional[str] = None
    
    # 错误和重试
    error: Optional[str] = Field(default=None, sa_column=Column(Text))
    retry_count: int = 0
    
    # 关联关系
    workflow_run: Optional[WorkflowRunDB] = Relationship(back_populates="stage_runs")

