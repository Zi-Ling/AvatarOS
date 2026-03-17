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

    # 轻量查询字段
    started_at: Optional[datetime] = Field(default=None)
    ended_at: Optional[datetime] = Field(default=None)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# 5. ArtifactVersionRecord — 产物版本记录（含依赖追踪）
# ---------------------------------------------------------------------------
class ArtifactVersionRecord(SQLModel, table=True):
    """
    产物版本记录（含依赖追踪）。

    artifact_kind 用于交付筛选和 merge 影响分析：
        file / logical / delivery
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
