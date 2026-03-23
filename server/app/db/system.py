# app/db/system.py
"""
系统级数据表：审批、授权、KV状态、审计日志、执行会话、Planner调用记录
"""
from __future__ import annotations

from sqlmodel import SQLModel, Field, Column, JSON
from datetime import datetime, timezone
from typing import Optional, List
import uuid


class ExecutionSession(SQLModel, table=True):
    """
    执行会话 — Runtime 层的核心状态机对象。

    lifecycle status（生命周期）：
        created → planned → running → waiting
                                    → completed
                                    → failed
                                    → cancelled
                                    → archived

    result_status（执行结果，与 lifecycle 分离）：
        success / partial_success / failed / unknown
    """
    __tablename__ = "execution_sessions"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )

    # ── 长任务关联 ──────────────────────────────────────────────────
    task_session_id: Optional[str] = Field(default=None, index=True)  # 关联 TaskSession
    execution_type: Optional[str] = Field(default=None)
    # initial / resume / post_merge / post_rollback

    # ── 业务身份锚点 ──────────────────────────────────────────────────
    run_id: Optional[str] = Field(default=None, index=True)          # 对应 runs.id
    task_id: Optional[str] = Field(default=None, index=True)         # 对应 tasks.id
    request_id: Optional[str] = Field(default=None, index=True)      # 来自 HTTP/socket 请求 id
    trace_id: Optional[str] = Field(default=None, index=True)        # 分布式 trace id（供 inspector/replay）
    conversation_id: Optional[str] = Field(default=None, index=True) # 对应 chat session_id，供按对话过滤

    # ── 生命周期状态机 ────────────────────────────────────────────────
    status: str = Field(default="created", index=True)
    # created / planned / running / waiting / completed / failed / cancelled / archived

    # ── 执行结果（与 lifecycle 分离）─────────────────────────────────
    result_status: Optional[str] = Field(default=None)
    # success / partial_success / failed / unknown

    # ── 目标描述 ──────────────────────────────────────────────────────
    goal: Optional[str] = Field(default=None)

    # ── 执行上下文锚点 ────────────────────────────────────────────────
    workspace_path: Optional[str] = Field(default=None)

    # runtime 初始化参数快照（max_concurrent_graphs、limits 等）
    runtime_config_snapshot: Optional[dict] = Field(default=None, sa_column=Column(JSON))

    # guard 配置快照（workspace_root、default_policy 等），session 创建时一次性写入
    policy_snapshot: Optional[dict] = Field(default=None, sa_column=Column(JSON))

    # ── 聚合统计（planner 侧，命名明确） ─────────────────────────────
    total_nodes: int = Field(default=0)
    completed_nodes: int = Field(default=0)
    failed_nodes: int = Field(default=0)
    planner_invocations: int = Field(default=0)
    planner_tokens: int = Field(default=0)       # 仅 planner 侧 token 消耗
    planner_cost_usd: float = Field(default=0.0) # 仅 planner 侧成本

    # ── 错误信息 ──────────────────────────────────────────────────────
    error_message: Optional[str] = Field(default=None)

    # ── 时间戳 ────────────────────────────────────────────────────────
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    planned_at: Optional[datetime] = Field(default=None)
    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
    archived_at: Optional[datetime] = Field(default=None)


class PlannerInvocation(SQLModel, table=True):
    """
    Planner 每次调用记录（独立表，append-only）。

    替代原来塞在 execution_sessions.planner_snapshots JSON array 的做法，
    支持按 session 分页、按时间排序、单独审计。
    """
    __tablename__ = "planner_invocations"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
    )
    session_id: str = Field(index=True)
    invocation_index: int = Field(index=True)   # 第几次调用（1-based）
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # ── 统计 ──────────────────────────────────────────────────────────
    tokens_used: int = Field(default=0)
    cost_usd: float = Field(default=0.0)
    latency_ms: Optional[int] = Field(default=None)

    # ── 摘要（供列表/调试快速查看） ──────────────────────────────────
    input_summary: Optional[str] = Field(default=None)   # 截断摘要
    output_summary: Optional[str] = Field(default=None)  # 截断摘要

    # ── 完整内容（未截断，后续可升级为 artifact_id） ─────────────────
    full_input_json: Optional[str] = Field(default=None)
    full_output_json: Optional[str] = Field(default=None)


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
    status: str = Field(default="pending", index=True)
    user_comment: Optional[str] = Field(default=None)
    responded_at: Optional[datetime] = Field(default=None)

    # 审批类型和超时策略（持久化状态机扩展）
    approval_type: str = Field(default="quick", description="quick/standard/complex")
    parent_request_id: Optional[str] = Field(default=None, index=True, description="关联原审批 ID")
    timeout_action: str = Field(default="mark_timeout", description="mark_timeout/auto_fail/keep_waiting")


class Grant(SQLModel, table=True):
    """路径访问授权记录"""
    __tablename__ = "grants"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    approval_request_id: Optional[str] = Field(default=None, index=True)
    path_pattern: str = Field(index=True)
    operations: List[str] = Field(sa_column=Column(JSON))
    scope: str = Field(default="session")
    scope_id: Optional[str] = Field(default=None, index=True)
    granted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = Field(default=None)
    revoked: bool = Field(default=False)


class KVState(SQLModel, table=True):
    """跨步骤 KV 状态存储"""
    __tablename__ = "kv_state"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    scope: str = Field(index=True)
    scope_id: str = Field(index=True)
    key: str = Field(index=True)
    value: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    ttl_seconds: Optional[int] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = Field(default=None)


class AuditLog(SQLModel, table=True):
    """审计日志"""
    __tablename__ = "audit_logs"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True, index=True)
    event_type: str = Field(index=True)
    actor: Optional[str] = Field(default=None)
    resource: Optional[str] = Field(default=None)
    operation: Optional[str] = Field(default=None)
    outcome: str = Field(default="success")
    details: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
