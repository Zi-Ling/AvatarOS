"""
models.py — 自演化运行时数据模型

包含：
- 枚举类型（OutcomeStatus, FailureCategory, CandidateType, CandidateStatus, SideEffectType, PatternType）
- 事实层数据类（ExecutionTrace, StepRecord, ContentRef, ToolCallRecord, ArtifactSnapshot, OutcomeRecord, CostTelemetry, StepCostEntry, TraceHole）
- 派生层数据类（ReflectionOutput, EvidenceLink, CandidateRule）
- 学习候选数据类（LearningCandidate, CandidateContent, RollbackInfo, StatusChange, ConflictGroup）
- 基线与版本数据类（EvolutionVersion, CostBaseline）
- SQLModel 数据库表定义
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlmodel import Field, SQLModel


# ---------------------------------------------------------------------------
# 枚举类型
# ---------------------------------------------------------------------------

class OutcomeStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    BLOCKED = "blocked"
    UNSAFE = "unsafe"


class FailureCategory(str, Enum):
    GOAL_MISUNDERSTANDING = "goal_misunderstanding"
    WRONG_TOOL = "wrong_tool"
    BAD_PARAMETER = "bad_parameter"
    ENV_ISSUE = "env_issue"
    POLICY_BLOCK = "policy_block"
    VERIFICATION_FAIL = "verification_fail"


class CandidateType(str, Enum):
    PLANNER_RULE = "planner_rule"
    POLICY_HINT = "policy_hint"
    SKILL_SCORE = "skill_score"
    WORKFLOW_TEMPLATE = "workflow_template"
    MEMORY_FACT = "memory_fact"


class CandidateStatus(str, Enum):
    DRAFT = "draft"
    VALIDATING = "validating"
    SHADOW = "shadow"
    ACTIVE = "active"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"


class SideEffectType(str, Enum):
    FILE_WRITE = "file_write"
    NETWORK_REQUEST = "network_request"
    SYSTEM_COMMAND = "system_command"


class PatternType(str, Enum):
    SUCCESS_PATTERN = "success_pattern"
    FAILURE_PATTERN = "failure_pattern"


class PromotionTier(str, Enum):
    LOW_RISK_AUTO = "low_risk_auto"
    MEDIUM_RISK_VALIDATED = "medium_risk_validated"
    HIGH_RISK_HUMAN = "high_risk_human"


# ---------------------------------------------------------------------------
# 事实层模型（append-only）
# ---------------------------------------------------------------------------

@dataclass
class ContentRef:
    """大字段外置引用。content_hash 用于校验，path 指向实际存储位置。"""
    content_hash: str
    path: str
    summary: str = ""


@dataclass
class ToolCallRecord:
    tool_name: str
    arguments: Any = None
    arguments_ref: Optional[ContentRef] = None
    result: Any = None
    result_ref: Optional[ContentRef] = None
    latency_ms: int = 0


@dataclass
class StepRecord:
    step_id: str
    trace_id: str
    skill_name: str
    input_params: Any = None
    input_params_ref: Optional[ContentRef] = None
    output: Any = None
    output_ref: Optional[ContentRef] = None
    status: str = ""
    duration_ms: int = 0
    retry_count: int = 0
    error: Optional[str] = None
    tool_calls: List[ToolCallRecord] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TraceHole:
    """trace 数据缺失标记。"""
    step_id: str
    reason: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ArtifactSnapshot:
    artifact_id: str
    trace_id: str
    step_id: str
    artifact_type: str
    semantic_role: Optional[str] = None
    path: str = ""
    content_hash: str = ""
    size_bytes: int = 0
    producer_step_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class StepCostEntry:
    step_id: str
    tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_ms: int = 0
    model_name: str = ""


@dataclass
class CostTelemetry:
    trace_id: str
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_time_ms: int = 0
    total_steps: int = 0
    retry_count: int = 0
    side_effect_intensity: Dict[SideEffectType, int] = field(default_factory=dict)
    model_name: str = ""
    step_cost_breakdown: List[StepCostEntry] = field(default_factory=list)


@dataclass
class OutcomeRecord:
    outcome_id: str
    trace_id: str
    task_id: str
    status: OutcomeStatus
    failure_category: Optional[FailureCategory] = None
    summary: str = ""
    decision_basis: str = ""
    cost_telemetry_ref: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ExecutionTrace:
    trace_id: str
    task_id: str
    session_id: str
    goal: str
    task_type: str
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None
    steps: List[StepRecord] = field(default_factory=list)
    artifacts: List[ArtifactSnapshot] = field(default_factory=list)
    outcome: Optional[OutcomeRecord] = None
    cost_telemetry: Optional[CostTelemetry] = None
    user_feedback: List[str] = field(default_factory=list)
    trace_holes: List[TraceHole] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 派生层模型
# ---------------------------------------------------------------------------

@dataclass
class EvidenceLink:
    """结构化证据引用，不使用松散字符串。"""
    trace_id: str
    step_id: Optional[str] = None
    artifact_id: Optional[str] = None
    verifier_result_id: Optional[str] = None
    description: str = ""


@dataclass
class CandidateRule:
    """反思引擎输出的候选规则（尚未成为 LearningCandidate）。"""
    type: CandidateType
    scope: str
    content: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    rationale: str = ""


@dataclass
class ReflectionOutput:
    reflection_id: str
    trace_id: str
    root_cause: str
    pattern_type: PatternType
    transferable_pattern: str
    evidence_links: List[EvidenceLink] = field(default_factory=list)
    candidate_rules: List[CandidateRule] = field(default_factory=list)
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# 学习候选模型
# ---------------------------------------------------------------------------

@dataclass
class CandidateContent:
    """结构化 diff，不使用大段文本对比。"""
    before_value: Any = None
    after_value: Any = None


@dataclass
class RollbackInfo:
    """回滚所需信息。"""
    before_value: Any = None
    rollback_steps: List[str] = field(default_factory=list)


@dataclass
class StatusChange:
    """状态变更记录（append-only）。"""
    from_status: CandidateStatus
    to_status: CandidateStatus
    reason: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class LearningCandidate:
    candidate_id: str
    type: CandidateType
    scope: str
    content: CandidateContent = field(default_factory=CandidateContent)
    evidence_links: List[EvidenceLink] = field(default_factory=list)
    confidence: float = 0.0
    status: CandidateStatus = CandidateStatus.DRAFT
    rollback_info: RollbackInfo = field(default_factory=RollbackInfo)
    source_reflection_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status_history: List[StatusChange] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


@dataclass
class ConflictGroup:
    """冲突候选组。"""
    conflict_group_id: str
    scope: str
    candidate_ids: List[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    """ValidationGate single-candidate result."""
    candidate_id: str
    passed: bool
    replay_passed: bool = True
    safety_passed: bool = True
    cost_passed: bool = True
    confidence_passed: bool = True
    evidence_sufficient: bool = True
    regression_details: List[str] = field(default_factory=list)
    reason: str = ""


# ---------------------------------------------------------------------------
# 基线与版本模型
# ---------------------------------------------------------------------------

@dataclass
class EvolutionVersion:
    version_id: str
    version_number: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    changes: List[str] = field(default_factory=list)
    rollback_info: Optional[Dict[str, Any]] = None


@dataclass
class CostBaseline:
    """任务类型的成本基线统计。"""
    task_type: str
    sample_count: int = 0
    median_tokens: float = 0.0
    mean_tokens: float = 0.0
    token_values: List[int] = field(default_factory=list)
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# SQLModel 数据库表定义
# ---------------------------------------------------------------------------

class ExecutionTraceDB(SQLModel, table=True):
    __tablename__ = "evolution_traces"
    trace_id: str = Field(primary_key=True)
    task_id: str = Field(index=True)
    session_id: str = Field(index=True)
    goal: str
    task_type: str = Field(index=True)
    start_time: datetime
    end_time: Optional[datetime] = None
    user_feedback: Optional[str] = None      # JSON serialized List[str]
    trace_holes: Optional[str] = None        # JSON serialized List[TraceHole]


class StepRecordDB(SQLModel, table=True):
    __tablename__ = "evolution_step_records"
    id: Optional[int] = Field(default=None, primary_key=True)
    step_id: str = Field(index=True)
    trace_id: str = Field(index=True, foreign_key="evolution_traces.trace_id")
    skill_name: str
    input_summary: str = ""
    input_ref_hash: Optional[str] = None
    input_ref_path: Optional[str] = None
    output_summary: str = ""
    output_ref_hash: Optional[str] = None
    output_ref_path: Optional[str] = None
    status: str
    duration_ms: int = 0
    retry_count: int = 0
    error: Optional[str] = None
    tool_calls: Optional[str] = None         # JSON serialized
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ArtifactSnapshotDB(SQLModel, table=True):
    __tablename__ = "evolution_artifact_snapshots"
    artifact_id: str = Field(primary_key=True)
    trace_id: str = Field(index=True, foreign_key="evolution_traces.trace_id")
    step_id: str
    artifact_type: str
    semantic_role: Optional[str] = None
    path: str = ""
    content_hash: str = ""
    size_bytes: int = 0
    producer_step_id: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OutcomeRecordDB(SQLModel, table=True):
    __tablename__ = "evolution_outcomes"
    outcome_id: str = Field(primary_key=True)
    trace_id: str = Field(index=True, foreign_key="evolution_traces.trace_id")
    task_id: str = Field(index=True)
    status: str = Field(index=True)
    failure_category: Optional[str] = None
    summary: str = ""
    decision_basis: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CostTelemetryDB(SQLModel, table=True):
    __tablename__ = "evolution_cost_telemetry"
    id: Optional[int] = Field(default=None, primary_key=True)
    trace_id: str = Field(index=True, foreign_key="evolution_traces.trace_id")
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_time_ms: int = 0
    total_steps: int = 0
    retry_count: int = 0
    side_effect_intensity: Optional[str] = None  # JSON: {"file_write": 3, ...}
    model_name: str = ""
    step_cost_breakdown: Optional[str] = None    # JSON serialized


class LearningCandidateDB(SQLModel, table=True):
    __tablename__ = "evolution_candidates"
    candidate_id: str = Field(primary_key=True)
    type: str = Field(index=True)
    scope: str = Field(index=True)
    content: str                              # JSON serialized CandidateContent
    evidence_links: str = "[]"                # JSON serialized
    confidence: float = 0.0
    status: str = Field(index=True, default="draft")
    rollback_info: str = "{}"                 # JSON serialized
    source_reflection_id: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    tags: str = "[]"                          # JSON serialized


class StatusChangeDB(SQLModel, table=True):
    __tablename__ = "evolution_status_changes"
    id: Optional[int] = Field(default=None, primary_key=True)
    candidate_id: str = Field(index=True, foreign_key="evolution_candidates.candidate_id")
    from_status: str
    to_status: str
    reason: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CostBaselineDB(SQLModel, table=True):
    __tablename__ = "evolution_cost_baselines"
    task_type: str = Field(primary_key=True)
    sample_count: int = 0
    median_tokens: float = 0.0
    mean_tokens: float = 0.0
    token_values: str = "[]"                  # JSON: recent N samples
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EvolutionVersionDB(SQLModel, table=True):
    __tablename__ = "evolution_versions"
    version_id: str = Field(primary_key=True)
    version_number: int = Field(index=True)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    changes: str = "[]"                       # JSON serialized
    rollback_info: Optional[str] = None       # JSON serialized
