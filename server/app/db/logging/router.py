# app/db/logging/router.py
"""
Router 日志数据模型
"""
from __future__ import annotations

from sqlmodel import SQLModel, Field, Column, JSON
from datetime import datetime, timezone
from typing import Optional
import uuid


class RouterRequest(SQLModel, table=True):
    """
    Router 请求日志模型
    
    记录每一次通过 Router 的用户请求
    """
    __tablename__ = "router_requests"
    
    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    request_id: str = Field(unique=True, index=True)  # 业务层的请求 ID
    
    # 输入信息
    input_text: str
    
    # 路由决策
    route_type: Optional[str] = Field(default=None)  # "chat" / "task" / "unknown"
    target: Optional[str] = Field(default=None)  # "avatar" / "llm_direct"
    intent_spec: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    
    # 关联信息
    task_id: Optional[str] = Field(default=None, index=True)  # 如果路由到任务，记录 task_id
    
    # 时间信息
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = Field(default=None)
    
    # 元数据
    meta: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    
    def __repr__(self):
        return f"<RouterRequest {self.id[:8]} route={self.route_type} input='{self.input_text[:30]}...'>"

