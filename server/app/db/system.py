# app/db/system.py
"""
系统级数据表：审批、授权、KV状态、审计日志
原来散落在 approval.db / state.db / audit.db，统一迁入 avatar.db
"""
from __future__ import annotations

from sqlmodel import SQLModel, Field, Column, JSON
from datetime import datetime, timezone
from typing import Optional, List
import uuid


class ApprovalRequest(SQLModel, table=True):
    """审批请求记录"""
    __tablename__ = "approval_requests"

    request_id: str = Field(primary_key=True)
    task_id: Optional[str] = Field(default=None, index=True)
    step_id: Optional[str] = Field(default=None)
    message: str
    operation: str
    details: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = Field(default=None)
    status: str = Field(default="pending", index=True)  # pending/approved/denied/expired/timeout
    user_comment: Optional[str] = Field(default=None)
    responded_at: Optional[datetime] = Field(default=None)


class Grant(SQLModel, table=True):
    """路径访问授权记录（持久化，有时效）"""
    __tablename__ = "grants"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
    )
    # 关联的审批请求
    approval_request_id: Optional[str] = Field(default=None, index=True)

    # 授权范围
    path_pattern: str = Field(index=True)   # e.g. "D:/reports/**" or "D:/reports/a.txt"
    operations: List[str] = Field(sa_column=Column(JSON))  # ["read","write","delete"]

    # 授权时效
    scope: str = Field(default="session")   # task | session | permanent
    scope_id: Optional[str] = Field(default=None, index=True)  # task_id or session_id

    granted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = Field(default=None)

    # 是否仍有效
    revoked: bool = Field(default=False)


class KVState(SQLModel, table=True):
    """跨步骤 KV 状态存储（原 state.db）"""
    __tablename__ = "kv_state"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
    )
    scope: str = Field(index=True)          # task | session | user
    scope_id: str = Field(index=True)       # task_id / session_id / user_id
    key: str = Field(index=True)
    value: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    ttl_seconds: Optional[int] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = Field(default=None)


class AuditLog(SQLModel, table=True):
    """审计日志（原 audit.db）"""
    __tablename__ = "audit_logs"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    event_type: str = Field(index=True)     # fs.write / approval.granted / etc.
    actor: Optional[str] = Field(default=None)   # task_id / session_id
    resource: Optional[str] = Field(default=None)  # 操作对象（路径、资源名）
    operation: Optional[str] = Field(default=None)
    outcome: str = Field(default="success")  # success / denied / error
    details: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
