"""L1 适配器层数据模型：枚举、Pydantic 模型、错误码映射。"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, model_validator


# ── 能力子分类 ────────────────────────────────────────────────────────

class CapabilityClass(str, Enum):
    """L1 适配器能力子分类"""
    LOCAL_STRUCTURED = "local_structured"
    NETWORK_STRUCTURED = "network_structured"
    COMMAND_EXEC = "command_exec"


# ── 副作用类型 ────────────────────────────────────────────────────────

class SideEffectType(str, Enum):
    """操作副作用类型"""
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    NETWORK_EGRESS = "network_egress"
    PROCESS_EXEC = "process_exec"


# ── 目标类型 ──────────────────────────────────────────────────────────

class TargetType(str, Enum):
    """执行请求目标类型"""
    FILE_OPERATION = "file_operation"
    API_CALL = "api_call"
    BROWSER_INTERACTION = "browser_interaction"
    DESKTOP_APP = "desktop_app"
    SHELL_COMMAND = "shell_command"
    UNKNOWN = "unknown"


# ── 风险等级 ──────────────────────────────────────────────────────────

class RiskLevel(str, Enum):
    """执行请求风险等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ── 适配器类型 ────────────────────────────────────────────────────────

class AdapterType(str, Enum):
    """适配器类型"""
    L1 = "L1"
    L3 = "L3"


# ── 安全级别 ──────────────────────────────────────────────────────────

class SecurityLevel(str, Enum):
    """操作安全级别"""
    ALLOWED = "allowed"
    APPROVAL_REQUIRED = "approval_required"
    FORBIDDEN = "forbidden"


# ── L1 标准化错误码 ──────────────────────────────────────────────────

class NativeAdapterErrorCode(str, Enum):
    """L1 适配器标准化错误码"""
    COMMAND_NOT_FOUND = "command_not_found"
    COMMAND_TIMEOUT = "command_timeout"
    COMMAND_FAILED = "command_failed"
    PERMISSION_DENIED = "permission_denied"
    INVALID_PARAMS = "invalid_params"
    ADAPTER_NOT_FOUND = "adapter_not_found"
    ADAPTER_INIT_FAILED = "adapter_init_failed"
    OUTPUT_PARSE_ERROR = "output_parse_error"
    SECURITY_BLOCKED = "security_blocked"
    APPROVAL_TIMEOUT = "approval_timeout"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    UNKNOWN = "unknown"


NATIVE_ADAPTER_ERROR_DEGRADABLE: dict[NativeAdapterErrorCode, bool] = {
    NativeAdapterErrorCode.COMMAND_NOT_FOUND: True,
    NativeAdapterErrorCode.COMMAND_TIMEOUT: True,
    NativeAdapterErrorCode.COMMAND_FAILED: False,
    NativeAdapterErrorCode.PERMISSION_DENIED: False,
    NativeAdapterErrorCode.INVALID_PARAMS: False,
    NativeAdapterErrorCode.ADAPTER_NOT_FOUND: True,
    NativeAdapterErrorCode.ADAPTER_INIT_FAILED: True,
    NativeAdapterErrorCode.OUTPUT_PARSE_ERROR: True,
    NativeAdapterErrorCode.SECURITY_BLOCKED: False,
    NativeAdapterErrorCode.APPROVAL_TIMEOUT: False,
    NativeAdapterErrorCode.RESOURCE_EXHAUSTED: False,
    NativeAdapterErrorCode.UNKNOWN: True,
}

NATIVE_ADAPTER_ERROR_DESCRIPTIONS: dict[NativeAdapterErrorCode, str] = {
    NativeAdapterErrorCode.COMMAND_NOT_FOUND: "命令未找到",
    NativeAdapterErrorCode.COMMAND_TIMEOUT: "命令执行超时",
    NativeAdapterErrorCode.COMMAND_FAILED: "命令执行失败",
    NativeAdapterErrorCode.PERMISSION_DENIED: "权限不足",
    NativeAdapterErrorCode.INVALID_PARAMS: "参数校验失败",
    NativeAdapterErrorCode.ADAPTER_NOT_FOUND: "适配器未找到",
    NativeAdapterErrorCode.ADAPTER_INIT_FAILED: "适配器初始化失败",
    NativeAdapterErrorCode.OUTPUT_PARSE_ERROR: "输出解析失败",
    NativeAdapterErrorCode.SECURITY_BLOCKED: "操作被安全策略禁止",
    NativeAdapterErrorCode.APPROVAL_TIMEOUT: "审批超时",
    NativeAdapterErrorCode.RESOURCE_EXHAUSTED: "资源配额耗尽",
    NativeAdapterErrorCode.UNKNOWN: "未知错误",
}


# ── 执行层标识 ────────────────────────────────────────────────────────

class ExecutionLayer(str, Enum):
    """执行层标识"""
    L1_NATIVE = "L1"
    L2_BROWSER = "L2"
    L3_BRIDGE = "L3"
    L4_COMPUTER_USE = "L4"


# ── Pydantic 模型 ────────────────────────────────────────────────────

class OperationDef(BaseModel):
    """单个操作定义"""
    operation_name: str
    description: str = ""
    input_schema: dict[str, Any] = {}
    output_schema: dict[str, Any] = {}
    capability_class: CapabilityClass = CapabilityClass.LOCAL_STRUCTURED
    side_effect_type: SideEffectType = SideEffectType.READ
    approval_default: SecurityLevel = SecurityLevel.ALLOWED


class CapabilitySchema(BaseModel):
    """适配器能力声明"""
    adapter_name: str
    adapter_type: AdapterType
    supported_operations: list[OperationDef]
    version: str = "1.0.0"
    # L3 扩展字段
    discovery_endpoint: Optional[str] = None
    verification_required: Optional[bool] = None

    @model_validator(mode="after")
    def validate_operations_not_empty(self):
        if not self.supported_operations:
            raise ValueError("supported_operations 不能为空")
        return self


class ValidationResult(BaseModel):
    """参数校验结果"""
    valid: bool
    errors: list[str] = []


class NativeAdapterResult(BaseModel):
    """L1 适配器执行结果"""
    success: bool
    data: Any = None
    error_code: Optional[NativeAdapterErrorCode] = None
    error_message: Optional[str] = None
    duration_ms: float = 0.0


class AdapterFailureContext(BaseModel):
    """L1 适配器失败上下文"""
    layer: ExecutionLayer = ExecutionLayer.L1_NATIVE
    error_code: NativeAdapterErrorCode
    error_message: str
    retryable: bool = False
    degradable: bool = True
    adapter_name: str
    operation_name: str
    completed_operations: list[str] = []
    raw_stderr: Optional[str] = None
    exit_code: Optional[int] = None
    evidence: dict[str, Any] = {}

    def to_json(self) -> str:
        return self.model_dump_json()


class AdapterSummary(BaseModel):
    """适配器摘要信息"""
    name: str
    adapter_type: AdapterType
    capabilities: list[str]
    registered_at: datetime


class ExecutionContext(BaseModel):
    """适配器执行上下文"""
    instance_id: str
    timeout_seconds: int = 300
    working_directory: Optional[str] = None
    environment: dict[str, str] = {}


# ── 安全策略配置 ──────────────────────────────────────────────────────

class SecurityPolicyConfig(BaseModel):
    """安全策略配置"""
    overrides: dict[str, dict[str, SecurityLevel]] = {}
    whitelist_mode: bool = False
    whitelisted_commands: list[str] = []
    approval_timeout_seconds: int = 60
