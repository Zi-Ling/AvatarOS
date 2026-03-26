# app/db/long_task_models.py
"""
长任务持久化运行时系统的 SQLModel 数据表定义。

包含 9 个表：
- TaskSession: 长任务顶层生命周期容器
- PlanGraphSnapshot: 计划图完整快照
- PatchLogEntry: 计划图变更补丁日志（append-only）
- StepState: 步骤当前状态（可变，服务恢复和查询）
- ArtifactVersionRecord: 产物版本记录（含依赖追踪）
- ArtifactDependency: 产物依赖关系
- Checkpoint: 检查点
- ChangeRequestRecord: 变更请求记录
- TaskQueueEntry: 任务调度队列
"""
from __future__ import annotations

from sqlmodel import SQLModel, Field
from sqlalchemy import UniqueConstraint
from datetime import datetime, timezone
from typing import Optional
import uuid


# ---------------------------------------------------------------------------
# 1. TaskSession — 长任务顶层生命周期容器
# ---------------------------------------------------------------------------
class TaskSession(SQLModel, table=True):
    """
    长任务顶层生命周期容器。

    状态机：
        created / planning / executing / paused / interrupted /
        waiting_input / waiting_approval / resuming / completed / failed / cancelled
    """
    __tablename__ = "task_sessions"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    goal: str = Field(description="任务目标描述")
    status: str = Field(default="created", index=True)
    current_graph_id: Optional[str] = Field(default=None, index=True)
    current_graph_version: int = Field(default=0)
    config_json: Optional[str] = Field(default=None, description="任务级配置 JSON")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = Field(default=None)

    # Lease 字段（持久化状态机扩展）
    worker_id: Optional[str] = Field(default=None, description="持有 Lease 的 worker 标识")
    lease_expiry: Optional[datetime] = Field(default=None, description="Lease 过期时间")
    last_heartbeat_at: Optional[datetime] = Field(default=None, description="最后心跳时间")
    heartbeat_interval_s: int = Field(default=30, description="心跳间隔秒数")
    lease_timeout_s: int = Field(default=90, description="Lease 过期阈值秒数")

    # 转换元数据
    last_transition_reason: Optional[str] = Field(default=None, description="最后一次转换原因")
    recovery_chain_json: Optional[str] = Field(default=None, description="恢复链路 JSON")

    # 暂停上下文（AOS Workbench Continuity Card）
    pause_context_json: Optional[str] = Field(
        default=None,
        description="暂停时写入的上下文 JSON: {pause_reason, completed_steps_summary, next_planned_action, checkpoint_id}",
    )

    # Event Sequence 持久化
    last_event_sequence: int = Field(default=0, description="该任务最后发出的事件 sequence 号")


# ---------------------------------------------------------------------------
# 2. PlanGraphSnapshot — 计划图完整快照
# ---------------------------------------------------------------------------
class PlanGraphSnapshot(SQLModel, table=True):
    """计划图完整快照。"""
    __tablename__ = "plan_graph_snapshots"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    task_session_id: str = Field(index=True)
    graph_version: int = Field(index=True)
    graph_json: str = Field(description="ExecutionGraph 完整 JSON 序列化")
    snapshot_reason: str = Field(description="initial_plan / post_merge / pre_resume / periodic")
    change_source: str = Field(default="system", description="planner / user / system / recovery")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# 3. PatchLogEntry — 计划图变更补丁日志（append-only）
# ---------------------------------------------------------------------------
class PatchLogEntry(SQLModel, table=True):
    """计划图变更补丁日志（append-only）。"""
    __tablename__ = "patch_log"

    id: Optional[int] = Field(default=None, primary_key=True)
    task_session_id: str = Field(index=True)
    graph_version: int = Field(index=True, description="此 patch 产生的新版本号")
    operation: str = Field(
        description="add_node / remove_node / add_edge / remove_edge / status_change / replace_subgraph"
    )
    operation_params_json: str = Field(description="操作参数 JSON")
    diff_json: Optional[str] = Field(default=None, description="变更前后 diff")
    change_reason: str = Field(
        description="initial_plan / status_update / resume_rebind / change_merge / replan_after_failure"
    )
    change_source: str = Field(default="system", description="planner / user / system / recovery")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# 4. StepState — 步骤当前状态（可变，服务恢复和查询）
# ---------------------------------------------------------------------------
class StepState(SQLModel, table=True):
    """
    步骤当前状态（可变，服务恢复和查询）。

    字段分层设计：
    - 轻量查询字段（id / status / capability_name / started_at / ended_at）直接列存
    - 大 JSON 详情字段（input_snapshot_json / output_json / side_effect_summary_json）按需加载

    11 态状态机：
        pending / ready / running / success / failed / blocked /
        stale / skipped / cancelled / waiting / retry_scheduled
    """
    __tablename__ = "step_states"
    __table_args__ = (
        UniqueConstraint("task_session_id", "idempotency_key", name="uq_step_state_idempotency"),
    )

    id: str = Field(primary_key=True, description="step_node_id")
    task_session_id: str = Field(index=True)
    graph_version: int = Field(description="最后更新时的 graph 版本")
    status: str = Field(index=True)
    capability_name: str = Field(description="Capability 名称")

    # 大 JSON 详情字段 — 按需加载
    input_snapshot_json: Optional[str] = Field(default=None, description="执行时输入参数快照")
    output_json: Optional[str] = Field(default=None, description="执行输出")
    side_effect_summary_json: Optional[str] = Field(default=None, description="副作用摘要")

    error_message: Optional[str] = Field(default=None)
    retry_count: int = Field(default=0)
    last_heartbeat_at: Optional[datetime] = Field(default=None)
    heartbeat_interval_s: int = Field(default=30)
    stale_threshold_s: int = Field(default=120)

    # 幂等字段（持久化状态机扩展）
    idempotency_key: Optional[str] = Field(default=None, description="task_id+node_id+input_hash")
    attempt_id: Optional[str] = Field(default=None, description="执行尝试标识")
    input_hash: Optional[str] = Field(default=None, description="输入参数 SHA-256")

    # 轻量查询字段
    started_at: Optional[datetime] = Field(default=None)
    ended_at: Optional[datetime] = Field(default=None)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# 5. ArtifactVersionRecord — 产物版本记录（含依赖追踪）
# ---------------------------------------------------------------------------
class ArtifactVersionRecord(SQLModel, table=True):
    """
    产物版本记录（含依赖追踪 + 版本 lineage）。

    artifact_kind 用于交付筛选和 merge 影响分析：
        file / logical / delivery

    version_source 标识版本产生原因：
        initial / iteration / repair / change_merge / manual
    """
    __tablename__ = "artifact_versions"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    task_session_id: str = Field(index=True)
    artifact_path: str = Field(index=True, description="文件路径")
    artifact_kind: str = Field(description="file / logical / delivery")
    producer_step_id: str = Field(index=True, description="产出步骤 ID")
    version: int = Field(default=1, description="版本号，单调递增")
    content_hash: str = Field(description="SHA-256")
    size: int = Field(description="字节数")
    mtime: float = Field(description="文件修改时间")
    stale_status: Optional[str] = Field(default=None, description="null / soft_stale / hard_stale")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # ── 版本 lineage（版本化骨架）────────────────────────────────────
    parent_version_id: Optional[str] = Field(
        default=None, index=True,
        description="上一版本的 ArtifactVersionRecord.id，v1 时为 null",
    )
    version_source: str = Field(
        default="initial",
        description="initial / iteration / repair / change_merge / manual",
    )


# ---------------------------------------------------------------------------
# 6. ArtifactDependency — 产物依赖关系
# ---------------------------------------------------------------------------
class ArtifactDependency(SQLModel, table=True):
    """产物依赖关系。"""
    __tablename__ = "artifact_dependencies"

    id: Optional[int] = Field(default=None, primary_key=True)
    task_session_id: str = Field(index=True)
    upstream_artifact_id: str = Field(index=True)
    downstream_artifact_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# 7. Checkpoint — 检查点
# ---------------------------------------------------------------------------
class Checkpoint(SQLModel, table=True):
    """
    检查点。

    四级重要性：routine / milestone / merge / pre_risky
    """
    __tablename__ = "checkpoints"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    task_session_id: str = Field(index=True)
    importance: str = Field(index=True, description="routine / milestone / merge / pre_risky")
    reason: str = Field(description="创建原因")

    graph_snapshot_json: str = Field(description="Plan_Graph 完整序列化")
    step_states_json: str = Field(description="所有 Step_Node 状态快照")
    artifact_refs_json: str = Field(description="Artifact 引用列表（含版本号和 content_hash）")
    budget_info_json: Optional[str] = Field(default=None, description="预算使用信息")
    environment_snapshot_json: Optional[str] = Field(default=None, description="环境快照")

    checksum: str = Field(description="Checkpoint 数据完整性校验值")
    graph_version: int = Field(description="对应的 graph 版本号")

    # 持久化状态机扩展字段
    execution_frontier_json: Optional[str] = Field(default=None, description="执行前沿快照")
    idempotency_metadata_json: Optional[str] = Field(default=None, description="幂等键映射快照")
    effect_ledger_snapshot_json: Optional[str] = Field(default=None, description="副作用账本快照")
    pending_requests_json: Optional[str] = Field(default=None, description="待处理审批请求快照")

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_deleted: bool = Field(default=False, description="软删除标记，保留策略使用")


# ---------------------------------------------------------------------------
# 8. ChangeRequestRecord — 变更请求记录
# ---------------------------------------------------------------------------
class ChangeRequestRecord(SQLModel, table=True):
    """变更请求记录。"""
    __tablename__ = "change_requests"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    task_session_id: str = Field(index=True)
    category: str = Field(
        description="scope_change / style_change / constraint_change / correction / bug_fix / priority_change / delivery_change"
    )
    raw_input: str = Field(description="用户原始输入")
    parsed_description: Optional[str] = Field(default=None)
    parse_confidence: float = Field(default=0.0)
    ambiguity_flag: bool = Field(default=False)
    status: str = Field(
        default="pending",
        description="pending / clarifying / merged / rejected / rolled_back",
    )
    merge_result_json: Optional[str] = Field(default=None, description="合并结果（plan_diff 等）")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# 9. TaskQueueEntry — 任务调度队列
# ---------------------------------------------------------------------------
class TaskQueueEntry(SQLModel, table=True):
    """
    任务调度队列。

    priority_level: 1=user_explicit  2=resume  3=system_maintenance
    """
    __tablename__ = "task_queue"

    id: Optional[int] = Field(default=None, primary_key=True)
    task_session_id: str = Field(index=True)
    task_type: str = Field(description="long_task / simple_task")
    priority_level: int = Field(default=1, description="1=user_explicit 2=resume 3=system_maintenance")
    status: str = Field(default="queued", index=True, description="queued / running / completed / cancelled")
    enqueued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)


# ---------------------------------------------------------------------------
# 10. EffectLedgerEntry — 副作用账本
# ---------------------------------------------------------------------------
class EffectLedgerEntry(SQLModel, table=True):
    """副作用账本条目。"""
    __tablename__ = "effect_ledger"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    task_session_id: str = Field(index=True)
    step_id: str = Field(index=True)
    effect_type: str = Field(description="fs/network/exec/human/browser 等")
    status: str = Field(default="prepared", index=True, description="prepared/committed/unknown/compensated")
    external_request_id: Optional[str] = Field(default=None, description="外部请求 ID")
    target_path: Optional[str] = Field(default=None, description="目标路径")
    content_hash: Optional[str] = Field(default=None, description="文件 hash")
    remote_receipt: Optional[str] = Field(default=None, description="远端回执")
    metadata_json: Optional[str] = Field(default=None, description="额外元数据")
    compensation_details: Optional[str] = Field(default=None, description="补偿操作详情")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# 11. GateRequestRecord — 持久化人机协作门控请求
# ---------------------------------------------------------------------------
class GateRequestRecord(SQLModel, table=True):
    """Persistent gate request for human-in-the-loop collaboration.

    Lifecycle: active → answered → merged | expired | cancelled
    Supports idempotent response via gate_id + version.
    """
    __tablename__ = "gate_requests"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    task_session_id: str = Field(index=True)
    session_id: str = Field(default="", index=True, description="ExecutionSession / conversation ID")
    gate_type: str = Field(description="clarification / approval / confirmation / missing_input")
    status: str = Field(default="active", index=True, description="active / answered / merged / expired / cancelled")
    version: int = Field(default=1, description="Monotonic version for idempotent response")

    # Request payload
    trigger_reason: str = Field(default="")
    blocking_questions_json: Optional[str] = Field(default=None, description="JSON array of blocking questions")
    required_info_json: Optional[str] = Field(default=None, description="JSON dict of required info")
    pending_assumptions_json: Optional[str] = Field(default=None, description="JSON array of assumptions for batch display")

    # Response payload (filled when user answers)
    answers_json: Optional[str] = Field(default=None, description="JSON dict of user answers")
    answered_at: Optional[datetime] = Field(default=None)

    # Merge tracking
    merge_target: Optional[str] = Field(default=None, description="Where answers were merged: task_definition / env_context / plan_inputs")
    merged_at: Optional[datetime] = Field(default=None)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# 12. SubtaskGraphSnapshot — multi-agent SubtaskGraph 持久化快照
# ---------------------------------------------------------------------------
class SubtaskGraphSnapshot(SQLModel, table=True):
    """Persistent snapshot of a SubtaskGraph for gate resume and crash recovery.

    Saved when execution enters WAITING_INPUT (gate) or at periodic checkpoints.
    Restored on gate resume to continue from the interrupted point.
    """
    __tablename__ = "subtask_graph_snapshots"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    task_session_id: str = Field(index=True)
    graph_id: str = Field(index=True, description="SubtaskGraph.graph_id")
    graph_json: str = Field(description="SubtaskGraph.to_dict() JSON serialization")
    results_json: Optional[str] = Field(default=None, description="Completed subtask results JSON")
    snapshot_reason: str = Field(default="gate_waiting", description="gate_waiting / checkpoint / pre_replan")
    exec_mode: str = Field(default="multi_agent", description="Execution mode at snapshot time")
    intent: str = Field(default="", description="Original intent for re-execution")
    env_context_json: Optional[str] = Field(default=None, description="Serialized env_context subset for resume")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# 13. CustomRoleRecord — 持久化自定义 Worker 角色
# ---------------------------------------------------------------------------
class CustomRoleRecord(SQLModel, table=True):
    """Persistent custom worker role definition.

    Loaded on startup to restore dynamically registered roles.
    """
    __tablename__ = "custom_roles"

    role_name: str = Field(primary_key=True)
    system_prompt: str = Field(description="Role system prompt / goal_tracker_hint")
    allowed_skills_json: Optional[str] = Field(default=None, description="JSON array of allowed skills")
    prohibited_skills_json: Optional[str] = Field(default=None, description="JSON array of prohibited skills")
    budget_multiplier: float = Field(default=1.0)
    skill_reason: str = Field(default="")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
