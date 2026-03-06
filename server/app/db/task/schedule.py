from sqlmodel import SQLModel, Field, Column, JSON
from datetime import datetime, timezone
from typing import Optional, List
import uuid

class Schedule(SQLModel, table=True):
    __tablename__ = "schedules"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    
    name: str = Field(index=True)
    description: Optional[str] = None
    
    # Trigger Rules (Cron-like)
    # Simplified for APScheduler usage
    cron_expression: str = Field(..., description="Standard cron expression e.g. '0 9 * * *'")
    
    # Task Definition (Intent Spec to be executed)
    intent_spec: dict = Field(sa_column=Column(JSON, nullable=False))
    
    # 🔗 任务依赖 (Task Dependencies)
    # 存储依赖的任务ID列表，只有当所有依赖任务最近一次执行成功时才执行
    depends_on: Optional[List[str]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    
    # Status
    is_active: bool = Field(default=True)
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<Schedule {self.id[:8]} '{self.name}' cron='{self.cron_expression}'>"

