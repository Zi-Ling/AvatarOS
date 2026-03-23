# server/app/services/workflow/models.py
"""
工作流编排系统数据模型。

包含：
- 枚举类型（6 个）
- Pydantic 模型（5 个，嵌入 JSON）
- SQLModel 表（7 张）
- 状态机转换表（2 个）
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, model_validator
from sqlmodel import Column, Field, JSON, SQLModel


# ---------------------------------------------------------------------------
# 枚举类型
# ---------------------------------------------------------------------------

class StepExecutorType(str, Enum):
    SKILL = "skill"
    TASK_SESSION = "task_session"
    BROWSER_AUTOMATION = "browser_automation"
    NATIVE_ADAPTER = "native_adapter"
    ROUTED = "routed"


class StepFailurePolicy(str, Enum):
    FAIL_FAST = "fail_fast"
    CONTINUE = "continue"
    RETRY = "retry"


class InstanceStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class TriggerType(str, Enum):
    MANUAL = "manual"
    CRON = "cron"
    API = "api"
    WORKFLOW_COMPLETED = "workflow_completed"


class VersionMode(str, Enum):
    FIXED = "fixed"
    LATEST = "latest"


# ---------------------------------------------------------------------------
# Pydantic 模型（嵌入 JSON 存储）
# ---------------------------------------------------------------------------

class ConditionExpr(BaseModel):
    """条件表达式（链表结构）"""
    left: str  # "steps.<step_id>.outputs.<key>"
    operator: Literal["==", "!=", ">", "<", ">=", "<="]
    right: Any
    logic: Optional[Literal["and", "or"]] = None
    next: Optional[ConditionExpr] = None


class StepOutputDef(BaseModel):
    """步骤输出声明"""
    key: str
    type: Literal["string", "number", "boolean", "json", "file_path", "binary"]
    required: bool = True
    description: str = ""


class WorkflowStepDef(BaseModel):
    """模板中的步骤定义"""
    step_id: str
    name: str
    executor_type: Literal["skill", "task_session", "browser_automation", "native_adapter", "routed"]
    capability_name: Optional[str] = None
    goal: Optional[str] = None
    params: dict[str, Any] = {}
    outputs: list[StepOutputDef] = []
    timeout_seconds: int = 1800
    failure_policy: Optional[Literal["fail_fast", "continue", "retry"]] = None
    retry_max: int = 3
    condition: Optional[ConditionExpr] = None

    @model_validator(mode="after")
    def validate_executor_fields(self):
        if self.executor_type == "skill" and not self.capability_name:
            raise ValueError("skill 类型步骤必须指定 capability_name")
        if self.executor_type == "task_session" and not self.goal:
            raise ValueError("task_session 类型步骤必须指定 goal")
        if self.executor_type == "browser_automation" and "actions" not in self.params:
            raise ValueError("browser_automation 类型步骤必须在 params 中包含 actions")
        if self.executor_type == "native_adapter":
            if "adapter_name" not in self.params:
                raise ValueError("native_adapter 类型步骤必须在 params 中包含 adapter_name")
            if "operation_name" not in self.params:
                raise ValueError("native_adapter 类型步骤必须在 params 中包含 operation_name")
        if self.executor_type == "routed":
            if "target_description" not in self.params:
                raise ValueError("routed 类型步骤必须在 params 中包含 target_description")
        return self


class WorkflowEdgeDef(BaseModel):
    """步骤间依赖/数据流定义"""
    source_step_id: str
    source_output_key: str
    target_step_id: str
    target_param_key: str
    optional: bool = False  # False=强依赖, True=弱依赖


class WorkflowParamDef(BaseModel):
    """模板参数定义"""
    name: str
    type: Literal["string", "number", "boolean", "file_path"]
    default: Optional[Any] = None
    required: bool = True
    description: str = ""


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


def compute_content_hash(
    steps: list[dict],
    edges: list[dict],
    parameters: list[dict],
    global_failure_policy: str,
) -> str:
    """对模板内容计算规范化 SHA-256，用于去重版本。"""
    canonical = json.dumps(
        {"steps": steps, "edges": edges, "parameters": parameters,
         "policy": global_failure_policy},
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# SQLModel 表
# ---------------------------------------------------------------------------

class WorkflowTemplate(SQLModel, table=True):
    """工作流模板"""
    __tablename__ = "wf_orchestration_templates"

    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str = Field(index=True)
    description: str = Field(default="")
    tags: list = Field(default_factory=list, sa_column=Column(JSON))
    latest_version_id: Optional[str] = Field(default=None)
    is_deleted: bool = Field(default=False)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class WorkflowTemplateVersion(SQLModel, table=True):
    """工作流模板版本（每次更新创建新版本）"""
    __tablename__ = "wf_orchestration_template_versions"

    id: str = Field(default_factory=_uuid, primary_key=True)
    template_id: str = Field(index=True)
    version_number: int = Field(default=1)
    steps: list = Field(default_factory=list, sa_column=Column(JSON))
    edges: list = Field(default_factory=list, sa_column=Column(JSON))
    parameters: list = Field(default_factory=list, sa_column=Column(JSON))
    global_failure_policy: str = Field(default="fail_fast")
    content_hash: str = Field(default="", index=True)
    created_at: datetime = Field(default_factory=_now)


class WorkflowInstance(SQLModel, table=True):
    """工作流实例（模板的一次具体执行）"""
    __tablename__ = "wf_orchestration_instances"

    id: str = Field(default_factory=_uuid, primary_key=True)
    template_id: str = Field(index=True)
    template_version_id: str = Field(index=True)
    execution_context_id: str = Field(default_factory=_uuid, index=True)
    status: str = Field(default="created", index=True)
    params: dict = Field(default_factory=dict, sa_column=Column(JSON))
    outputs: dict = Field(default_factory=dict, sa_column=Column(JSON))
    trigger_id: Optional[str] = Field(default=None)
    parent_instance_id: Optional[str] = Field(default=None)
    is_deleted: bool = Field(default=False)
    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class WorkflowStepRun(SQLModel, table=True):
    """步骤执行记录（聚合状态）"""
    __tablename__ = "wf_orchestration_step_runs"

    id: str = Field(default_factory=_uuid, primary_key=True)
    instance_id: str = Field(index=True)
    step_id: str
    status: str = Field(default="pending", index=True)
    executor_type: str
    child_task_session_id: Optional[str] = Field(default=None)
    inputs: dict = Field(default_factory=dict, sa_column=Column(JSON))
    outputs: dict = Field(default_factory=dict, sa_column=Column(JSON))
    error: Optional[str] = Field(default=None)
    retry_count: int = Field(default=0)
    started_at: Optional[datetime] = Field(default=None)
    ended_at: Optional[datetime] = Field(default=None)
    duration_ms: float = Field(default=0.0)


class WorkflowStepAttempt(SQLModel, table=True):
    """步骤每次尝试的明细记录"""
    __tablename__ = "wf_orchestration_step_attempts"

    id: str = Field(default_factory=_uuid, primary_key=True)
    step_run_id: str = Field(index=True)
    attempt_number: int
    status: str  # success / failed / timeout / cancelled
    outputs: dict = Field(default_factory=dict, sa_column=Column(JSON))
    error: Optional[str] = Field(default=None)
    started_at: datetime = Field(default_factory=_now)
    ended_at: Optional[datetime] = Field(default=None)
    duration_ms: float = Field(default=0.0)


class WorkflowTrigger(SQLModel, table=True):
    """工作流触发器"""
    __tablename__ = "wf_orchestration_triggers"

    id: str = Field(default_factory=_uuid, primary_key=True)
    template_id: str = Field(index=True)
    template_version_id: Optional[str] = Field(default=None)
    version_mode: str = Field(default="fixed")
    trigger_type: str = Field(index=True)
    cron_expression: Optional[str] = Field(default=None)
    source_workflow_template_id: Optional[str] = Field(default=None)
    filter_condition: Optional[str] = Field(default=None)
    default_params: dict = Field(default_factory=dict, sa_column=Column(JSON))
    is_active: bool = Field(default=True)
    schedule_id: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class WorkflowTriggerLog(SQLModel, table=True):
    """触发去重记录（workflow_completed 幂等保护）"""
    __tablename__ = "wf_orchestration_trigger_logs"

    id: str = Field(default_factory=_uuid, primary_key=True)
    trigger_id: str = Field(index=True)
    source_instance_id: str = Field(index=True)
    created_instance_id: str
    created_at: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# 状态机转换表
# ---------------------------------------------------------------------------

VALID_INSTANCE_TRANSITIONS: dict[str, set[str]] = {
    "created": {"running"},
    "running": {"paused", "completed", "failed", "cancelled"},
    "paused": {"running", "cancelled"},
    "failed": {"running"},      # retry
    "cancelled": {"running"},   # retry
}

VALID_STEP_RUN_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"running", "skipped", "cancelled"},
    "running": {"success", "failed", "cancelled"},
    "failed": {"pending"},      # retry 重置
    "skipped": {"pending"},     # retry 时前驱恢复后重新参与调度
    "success": set(),           # 终态
    "cancelled": set(),         # 终态
}

# 终态集合
INSTANCE_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
STEP_RUN_TERMINAL_STATUSES = {"success", "failed", "skipped", "cancelled"}
