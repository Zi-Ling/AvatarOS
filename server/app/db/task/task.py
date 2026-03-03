# app/db/task/task.py
"""
Task / Run / Step 数据模型（使用 SQLModel）
"""
# from __future__ import annotations  <-- 移除此行，避免类型注解变为字符串

from sqlmodel import SQLModel, Field, Relationship, Column, JSON
from datetime import datetime
from typing import Optional, List
import uuid


class Step(SQLModel, table=True):
    """
    步骤记录模型
    """
    __tablename__ = "steps"
    
    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    run_id: str = Field(foreign_key="runs.id", index=True)
    
    # 步骤信息
    step_index: int
    step_name: str
    skill_name: str
    
    status: str = Field(default="pending")
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = Field(default=None)
    finished_at: Optional[datetime] = Field(default=None)
    
    input_params: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    output_result: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    
    error_message: Optional[str] = Field(default=None)
    
    # 关联
    # 使用字符串前向引用，因为 Run 还没定义
    run: Optional["Run"] = Relationship(back_populates="steps")
    
    def __repr__(self):
        return f"<Step {self.id[:8]} run={self.run_id[:8]} skill={self.skill_name} status={self.status}>"
    
    @property
    def duration_ms(self) -> Optional[int]:
        if self.started_at and self.finished_at:
            return int((self.finished_at - self.started_at).total_seconds() * 1000)
        return None


class Run(SQLModel, table=True):
    """
    运行记录模型
    """
    __tablename__ = "runs"
    
    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    task_id: str = Field(foreign_key="tasks.id", index=True)
    
    status: str = Field(default="pending")
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = Field(default=None)
    finished_at: Optional[datetime] = Field(default=None)
    
    summary: Optional[str] = Field(default=None)
    error_message: Optional[str] = Field(default=None)
    
    # 关联
    # 使用字符串前向引用，因为 Task 还没定义
    task: Optional["Task"] = Relationship(back_populates="runs")
    # 使用直接类引用，因为 Step 已经定义
    steps: List[Step] = Relationship(back_populates="run", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    
    def __repr__(self):
        return f"<Run {self.id[:8]} task={self.task_id[:8]} status={self.status}>"
    
    @property
    def duration_seconds(self) -> Optional[float]:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


class Task(SQLModel, table=True):
    """
    任务模型
    """
    __tablename__ = "tasks"
    
    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    title: str
    intent_spec: dict = Field(sa_column=Column(JSON, nullable=False))
    task_mode: str = Field(default="one_shot")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # 关联
    # 使用直接类引用，因为 Run 已经定义
    runs: List[Run] = Relationship(back_populates="task", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    
    def __repr__(self):
        return f"<Task {self.id[:8]} '{self.title}'>"
