# app/db/logging/llm.py
"""
LLM 调用日志数据模型
"""
from __future__ import annotations

from sqlmodel import SQLModel, Field, Column, JSON
from datetime import datetime
from typing import Optional
import uuid


class LLMCall(SQLModel, table=True):
    """
    LLM 调用日志模型
    
    记录所有 LLM 调用的详细信息（来自 Router、Planner、Skills 等）
    """
    __tablename__ = "llm_calls"
    
    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    call_id: str = Field(index=True)  # 业务层的调用 ID
    
    # 来源信息
    source: str = Field(default="unknown")  # "router" / "planner" / "skill" / "other"
    parent_id: Optional[str] = Field(default=None, index=True)  # 关联的 request_id 或 step_id
    
    # LLM 信息
    model: Optional[str] = Field(default=None)
    prompt: Optional[str] = Field(default=None)
    response: Optional[str] = Field(default=None)
    
    # 时间信息
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = Field(default=None)
    latency_ms: Optional[float] = Field(default=None)
    
    # 状态
    success: bool = Field(default=False)
    error: Optional[str] = Field(default=None)
    
    # 使用情况
    usage: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    
    # 其他参数
    params: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    
    def __repr__(self):
        return f"<LLMCall {self.id[:8]} source={self.source} model={self.model} success={self.success}>"

