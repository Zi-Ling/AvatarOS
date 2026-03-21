"""
Structured Data Layer — 核心数据模型与错误码定义

所有数据类使用 dataclasses，枚举继承 str + Enum。
Python 3.13+，使用 from __future__ import annotations。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


# ── 字段类型 ──


class FieldType(str, Enum):
    TEXT = "text"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATETIME = "datetime"
    ENUM = "enum"
    REFERENCE = "reference"  # 引用其他 Business_Object
    COMPUTED = "computed"  # 派生字段（只读）


@dataclass
class FieldDefinition:
    """业务对象字段定义"""

    name: str
    field_type: FieldType
    required: bool = False
    enum_values: list[str] | None = None  # field_type=ENUM 时的可选值
    reference_to: str | None = None  # field_type=REFERENCE 时的目标对象类型
    readonly: bool = False  # 派生字段标记
    compute_key: str | None = None  # 派生字段映射到内置计算器函数名
    deprecated: bool = False  # 字段废弃标记（migration 保留列但不再使用）
    renamed_from: str | None = None  # 字段重命名来源（migration 用于数据迁移）
    indexed: bool = False  # 是否需要建索引


# ── 关联约束 ──


@dataclass
class RelationConstraint:
    """声明对象允许的关联关系"""

    relation_type: str  # owns/assigned_to/related_to/depends_on
    target_type: str  # 目标对象类型
    description: str = ""


# ── 对象定义 ──


@dataclass
class ObjectDefinition:
    """业务对象元数据定义"""

    name: str  # 对象类型名（如 "Contact"）
    fields: list[FieldDefinition]  # 业务字段（不含基础字段）
    description: str = ""
    schema_version: int = 1  # 对象 schema 版本，字段变更时递增
    allowed_relations: list[RelationConstraint] = field(default_factory=list)


# ── 基础字段（所有对象自动包含） ──
# 注：基础层不包含通用 status 字段，业务状态由各对象自定义字段承载

BASE_FIELDS: list[FieldDefinition] = [
    FieldDefinition(name="id", field_type=FieldType.TEXT, required=True),
    FieldDefinition(name="owner_id", field_type=FieldType.TEXT),
    FieldDefinition(name="workspace_id", field_type=FieldType.TEXT, required=True),
    FieldDefinition(name="created_at", field_type=FieldType.DATETIME),
    FieldDefinition(name="updated_at", field_type=FieldType.DATETIME),
    FieldDefinition(name="created_by", field_type=FieldType.TEXT),
    FieldDefinition(name="version", field_type=FieldType.INTEGER),
    FieldDefinition(name="archived_at", field_type=FieldType.DATETIME),
]


# ── 查询过滤器 ──
# MVP 仅支持顶层 AND 组合的 FilterCondition 列表


class FilterOperator(str, Enum):
    EQ = "eq"
    NEQ = "neq"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    LIKE = "like"
    IN = "in"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"


@dataclass
class FilterCondition:
    """查询条件（MVP 公开接口）"""

    field: str
    operator: FilterOperator
    value: Any = None  # is_null/is_not_null 时为 None


# ── 未来能力预留（MVP 不暴露） ──


class LogicOperator(str, Enum):
    AND = "and"
    OR = "or"


@dataclass
class FilterGroup_Future:
    """组合节点：逻辑组合（未来能力，MVP 不使用）"""

    logic: LogicOperator = LogicOperator.AND
    conditions: list[FilterCondition | FilterGroup_Future] = field(default_factory=list)


# ── 变更提案 ──


class ProposalStatus(str, Enum):
    PENDING = "pending"
    COMMITTED = "committed"
    REJECTED = "rejected"
    EXPIRED = "expired"


class OperationType(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    ARCHIVE = "archive"
    LINK = "link"
    # Schema-level operations
    CREATE_OBJECT = "create_object"
    ALTER_OBJECT = "alter_object"
    DROP_OBJECT = "drop_object"


# ── Schema 类型安全转换矩阵 ──
# key = (from_type, to_type), value = True 表示允许无损转换
SAFE_TYPE_CONVERSIONS: dict[tuple[str, str], bool] = {
    ("integer", "float"): True,
    ("integer", "text"): True,
    ("float", "text"): True,
    ("boolean", "text"): True,
    ("boolean", "integer"): True,
    ("datetime", "text"): True,
    ("enum", "text"): True,
    ("reference", "text"): True,
}


def is_safe_type_conversion(from_type: str, to_type: str) -> bool:
    """检查字段类型转换是否安全（宽化方向）"""
    if from_type == to_type:
        return True
    return SAFE_TYPE_CONVERSIONS.get((from_type, to_type), False)


@dataclass
class ChangeProposal:
    """变更提案"""

    proposal_id: str
    object_type: str
    operation: OperationType
    record_id: str | None  # create 时为 None
    changes: dict[str, Any]  # 字段变更内容
    summary: str  # 人类可读摘要
    diff_snapshot: dict[str, Any] | None  # update 时的 before/after
    risk_level: str = "low"  # low / high
    status: ProposalStatus = ProposalStatus.PENDING
    proposed_by: str = "system"
    approval_mode: str = "manual"  # auto / manual
    approved_by: str | None = None
    approved_at: datetime | None = None
    rejected_reason: str | None = None
    expected_version: int | None = None  # update/archive 时的乐观锁版本
    expires_at: datetime | None = None  # 提案过期时间（TTL）
    trace_id: str | None = None  # 关联 agent 执行链路
    workspace_id: str = ""
    created_at: datetime | None = None


# ── 审计日志 ──


@dataclass
class AuditLogEntry:
    """审计日志条目"""

    change_id: str
    object_type: str
    record_id: str
    operation: OperationType
    before_snapshot: dict[str, Any] | None  # create 时为 None
    after_snapshot: dict[str, Any]
    proposal_id: str | None
    actor: str
    trace_id: str | None = None  # 关联 agent run_id
    reason: str = ""
    changed_at: datetime | None = None


# ── 对象关联 ──


@dataclass
class ObjectRelation:
    """对象间关联关系"""

    relation_id: str
    relation_type: str  # owns/assigned_to/related_to/depends_on
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None


# ── 错误码体系 ──


class DataErrorCode(str, Enum):
    OBJECT_NOT_FOUND = "OBJECT_NOT_FOUND"
    RECORD_NOT_FOUND = "RECORD_NOT_FOUND"
    DUPLICATE_OBJECT = "DUPLICATE_OBJECT"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    INVALID_PROPOSAL = "INVALID_PROPOSAL"
    PROPOSAL_EXPIRED = "PROPOSAL_EXPIRED"
    PROPOSAL_ALREADY_COMMITTED = "PROPOSAL_ALREADY_COMMITTED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_FIELD = "INVALID_FIELD"
    UNSUPPORTED_QUERY = "UNSUPPORTED_QUERY"
    READONLY_FIELD = "READONLY_FIELD"
    INVALID_RELATION = "INVALID_RELATION"
    STORAGE_ERROR = "STORAGE_ERROR"
    WORKSPACE_MISMATCH = "WORKSPACE_MISMATCH"


@dataclass
class DataError:
    """结构化错误信息"""

    code: DataErrorCode
    detail: dict[str, Any]
    retryable: bool = False


# ── 自定义异常类 ──


class DuplicateObjectError(Exception):
    """注册重复的对象名称"""


class VersionConflictError(Exception):
    """乐观锁版本不匹配"""


class RecordNotFoundError(Exception):
    """记录不存在"""


class ObjectNotFoundError(Exception):
    """对象类型不存在"""


class ValidationError(Exception):
    """字段校验失败"""


class InvalidProposalError(Exception):
    """提案无效（不存在、状态非 pending、已过期等）"""


class ReadonlyFieldError(Exception):
    """尝试修改只读/派生字段"""


class InvalidFieldError(Exception):
    """引用不存在的字段"""


class StorageError(Exception):
    """数据库操作异常"""


class WorkspaceMismatchError(Exception):
    """workspace_id 不匹配"""


class UnsafeSchemaChangeError(Exception):
    """不安全的 schema 变更（类型收窄、数据可能丢失）"""
