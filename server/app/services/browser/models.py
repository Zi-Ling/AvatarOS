# server/app/services/browser/models.py
"""Browser Automation Executor 数据模型。"""
from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any, ClassVar, Literal, Optional

from pydantic import BaseModel, Field


# ── 操作原语类型 ──────────────────────────────────────────────────────

class ActionPrimitiveType(str, Enum):
    """操作原语类型"""
    # 基础原语
    NAVIGATE = "navigate"
    CLICK = "click"
    FILL = "fill"
    EXTRACT_TEXT = "extract_text"
    EXTRACT_TABLE = "extract_table"
    EXTRACT_LINKS = "extract_links"
    WAIT_FOR = "wait_for"
    SCREENSHOT = "screenshot"
    HOVER = "hover"
    SELECT_OPTION = "select_option"
    PRESS_KEY = "press_key"
    SCROLL = "scroll"
    EVALUATE_JS = "evaluate_js"
    # 组合原语
    UPLOAD_FILE = "upload_file"
    DOWNLOAD_WAIT = "download_wait"
    DRAG_DROP = "drag_drop"
    SWITCH_TAB = "switch_tab"
    CLOSE_TAB = "close_tab"
    HANDLE_DIALOG = "handle_dialog"
    SET_COOKIE = "set_cookie"
    GET_COOKIES = "get_cookies"


# ── 错误码 ────────────────────────────────────────────────────────────

class BrowserErrorCode(str, Enum):
    """标准化错误码"""
    SELECTOR_NOT_FOUND = "selector_not_found"
    ACTIONABILITY_TIMEOUT = "actionability_timeout"
    NAVIGATION_TIMEOUT = "navigation_timeout"
    NAVIGATION_FAILED = "navigation_failed"
    PAGE_CRASHED = "page_crashed"
    CONTEXT_DESTROYED = "context_destroyed"
    CROSS_ORIGIN_BLOCKED = "cross_origin_blocked"
    AUTH_REQUIRED = "auth_required"
    DIALOG_BLOCKED = "dialog_blocked"
    DOWNLOAD_FAILED = "download_failed"
    UPLOAD_FAILED = "upload_failed"
    JS_EVALUATION_ERROR = "js_evaluation_error"
    RATE_LIMITED = "rate_limited"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    SCRIPT_TIMEOUT = "script_timeout"
    FORBIDDEN_ACTION = "forbidden_action"
    UNKNOWN = "unknown"


BROWSER_ERROR_DEGRADABLE: dict[BrowserErrorCode, bool] = {
    BrowserErrorCode.SELECTOR_NOT_FOUND: True,
    BrowserErrorCode.ACTIONABILITY_TIMEOUT: True,
    BrowserErrorCode.NAVIGATION_TIMEOUT: True,
    BrowserErrorCode.NAVIGATION_FAILED: True,
    BrowserErrorCode.PAGE_CRASHED: True,
    BrowserErrorCode.CONTEXT_DESTROYED: False,
    BrowserErrorCode.CROSS_ORIGIN_BLOCKED: True,
    BrowserErrorCode.AUTH_REQUIRED: True,
    BrowserErrorCode.DIALOG_BLOCKED: True,
    BrowserErrorCode.DOWNLOAD_FAILED: False,
    BrowserErrorCode.UPLOAD_FAILED: False,
    BrowserErrorCode.JS_EVALUATION_ERROR: True,
    BrowserErrorCode.RATE_LIMITED: False,
    BrowserErrorCode.RESOURCE_EXHAUSTED: False,
    BrowserErrorCode.SCRIPT_TIMEOUT: True,
    BrowserErrorCode.FORBIDDEN_ACTION: False,
    BrowserErrorCode.UNKNOWN: True,
}

BROWSER_ERROR_DESCRIPTIONS: dict[BrowserErrorCode, str] = {
    BrowserErrorCode.SELECTOR_NOT_FOUND: "目标元素未找到",
    BrowserErrorCode.ACTIONABILITY_TIMEOUT: "可操作性检查超时",
    BrowserErrorCode.NAVIGATION_TIMEOUT: "页面导航超时",
    BrowserErrorCode.NAVIGATION_FAILED: "页面导航失败（HTTP 错误等）",
    BrowserErrorCode.PAGE_CRASHED: "页面崩溃",
    BrowserErrorCode.CONTEXT_DESTROYED: "浏览器上下文已销毁",
    BrowserErrorCode.CROSS_ORIGIN_BLOCKED: "跨域请求被阻止",
    BrowserErrorCode.AUTH_REQUIRED: "需要认证",
    BrowserErrorCode.DIALOG_BLOCKED: "对话框阻塞执行",
    BrowserErrorCode.DOWNLOAD_FAILED: "文件下载失败",
    BrowserErrorCode.UPLOAD_FAILED: "文件上传失败",
    BrowserErrorCode.JS_EVALUATION_ERROR: "JavaScript 执行错误",
    BrowserErrorCode.RATE_LIMITED: "请求频率受限",
    BrowserErrorCode.RESOURCE_EXHAUSTED: "资源配额耗尽",
    BrowserErrorCode.SCRIPT_TIMEOUT: "脚本执行超时",
    BrowserErrorCode.FORBIDDEN_ACTION: "操作被安全策略禁止",
    BrowserErrorCode.UNKNOWN: "未知错误",
}


# ── 可操作性失败原因 ──────────────────────────────────────────────────

class ActionabilityFailureReason(str, Enum):
    NOT_FOUND = "not_found"
    NOT_VISIBLE = "not_visible"
    NOT_STABLE = "not_stable"
    NOT_ENABLED = "not_enabled"
    OBSCURED_BY_OVERLAY = "obscured_by_overlay"
    IN_IFRAME_UNREACHABLE = "in_iframe_unreachable"
    OUTSIDE_VIEWPORT = "outside_viewport"
    DETACHED_FROM_DOM = "detached_from_dom"


# ── 选择器类型 ────────────────────────────────────────────────────────

class SelectorType(str, Enum):
    ROLE = "role"
    LABEL = "label"
    DATA_TESTID = "data_testid"
    CSS = "css"
    TEXT = "text"
    XPATH = "xpath"


SELECTOR_PRIORITY: dict[SelectorType, int] = {
    SelectorType.ROLE: 1,
    SelectorType.LABEL: 1,
    SelectorType.DATA_TESTID: 2,
    SelectorType.CSS: 3,
    SelectorType.TEXT: 4,
    SelectorType.XPATH: 5,
}


# ── 安全级别 ──────────────────────────────────────────────────────────

class SecurityLevel(str, Enum):
    ALLOWED = "allowed"
    APPROVAL_REQUIRED = "approval_required"
    FORBIDDEN = "forbidden"


# ── 验证策略 ──────────────────────────────────────────────────────────

class BrowserVerificationStrategy(str, Enum):
    ELEMENT_APPEARED = "element_appeared"
    ELEMENT_DISAPPEARED = "element_disappeared"
    TEXT_CONTAINS = "text_contains"
    TEXT_EQUALS = "text_equals"
    URL_CHANGED = "url_changed"
    URL_MATCHES = "url_matches"
    ELEMENT_COUNT = "element_count"
    ATTRIBUTE_EQUALS = "attribute_equals"


# ── 等待策略 ──────────────────────────────────────────────────────────

class WaitUntilStrategy(str, Enum):
    DOMCONTENTLOADED = "domcontentloaded"
    NETWORKIDLE = "networkidle"
    LOAD = "load"


# ── 失败策略 ──────────────────────────────────────────────────────────

class FailurePolicy(str, Enum):
    FAIL_FAST = "fail_fast"
    CONTINUE = "continue"


class PlaybackFailurePolicy(str, Enum):
    SKIP = "skip"
    RETRY = "retry"
    ABORT = "abort"


# ── 对话框处理 ────────────────────────────────────────────────────────

class DialogAction(str, Enum):
    ACCEPT = "accept"
    DISMISS = "dismiss"
    FILL_PROMPT = "fill_prompt"


# ── 等待状态 ──────────────────────────────────────────────────────────

class WaitForState(str, Enum):
    VISIBLE = "visible"
    HIDDEN = "hidden"
    ATTACHED = "attached"
    DETACHED = "detached"


# ═══════════════════════════════════════════════════════════════════════
# Pydantic 核心模型
# ═══════════════════════════════════════════════════════════════════════

# ── 选择器 ────────────────────────────────────────────────────────────

class SelectorCandidate(BaseModel):
    """选择器候选"""
    selector_type: SelectorType
    expression: str


class SelectorResolution(BaseModel):
    """选择器解析结果"""
    adopted: SelectorCandidate
    match_count: int
    quality_score: int  # 0-100
    all_candidates: list[SelectorCandidate] = []


# ── 验证规格 ──────────────────────────────────────────────────────────

class VerificationSpec(BaseModel):
    """验证规格"""
    strategy: BrowserVerificationStrategy
    selector: str | None = None
    expected: Any = None
    comparison: Literal["eq", "gt", "lt", "gte", "lte"] | None = None


# ── 操作原语 ──────────────────────────────────────────────────────────

class ActionPrimitive(BaseModel):
    """结构化操作原语"""
    action_type: ActionPrimitiveType
    selector: str | None = None
    selector_candidates: list[SelectorCandidate] = []
    params: dict[str, Any] = {}
    verification: VerificationSpec | None = None
    timeout_ms: int | None = None


# ── 可操作性检查结果 ──────────────────────────────────────────────────

class ActionabilityCheckDetail(BaseModel):
    """单级检查详情"""
    stage: str
    passed: bool
    duration_ms: float = 0.0


class ActionabilityResult(BaseModel):
    """可操作性检查结果"""
    actionable: bool
    failure_reason: ActionabilityFailureReason | None = None
    checks: list[ActionabilityCheckDetail] = []
    total_duration_ms: float = 0.0


# ── 页面状态快照 ──────────────────────────────────────────────────────

class InteractiveElementSummary(BaseModel):
    """可交互元素摘要"""
    selector: str
    tag: str
    text: str = ""
    role: str = ""
    enabled: bool = True


class FormFieldSummary(BaseModel):
    """表单字段摘要"""
    name: str
    field_type: str
    value: str = ""
    required: bool = False


class DialogInfo(BaseModel):
    """对话框信息"""
    dialog_type: str  # alert/confirm/prompt
    message: str = ""


class PageStateSnapshot(BaseModel):
    """结构化页面状态快照"""
    url: str
    title: str
    timestamp: datetime
    interactive_elements_summary: list[InteractiveElementSummary] = []
    form_fields: list[FormFieldSummary] = []
    active_dialogs: list[DialogInfo] = []
    download_status: dict[str, Any] | None = None
    viewport_size: dict[str, int] = {"width": 1280, "height": 800}
    scroll_position: dict[str, int] = {"x": 0, "y": 0}
    truncated: bool = False

    MAX_INTERACTIVE_ELEMENTS: ClassVar[int] = 50
    MAX_SERIALIZED_BYTES: ClassVar[int] = 64 * 1024  # 64KB


# ── 验证结果 ──────────────────────────────────────────────────────────

class BrowserVerificationResult(BaseModel):
    """验证结果"""
    passed: bool
    strategy: str
    expected: Any = None
    actual: Any = None
    detail: str = ""
    page_snapshot: PageStateSnapshot | None = None  # 失败时附带


# ── 操作结果 ──────────────────────────────────────────────────────────

class ActionResult(BaseModel):
    """单个操作的标准化结果"""
    success: bool
    data: Any = None
    error: str | None = None
    error_code: BrowserErrorCode | None = None
    duration_ms: float = 0.0
    selector_resolution: SelectorResolution | None = None
    verification_result: BrowserVerificationResult | None = None


class ExecutionResult(BaseModel):
    """操作序列的聚合结果"""
    success: bool
    action_results: list[ActionResult] = []
    final_page_state: PageStateSnapshot | None = None
    error_code: BrowserErrorCode | None = None
    error_message: str | None = None
    total_duration_ms: float = 0.0


# ── 会话模型 ──────────────────────────────────────────────────────────

class ResourceQuota(BaseModel):
    """资源配额跟踪"""
    max_artifacts: int = 50
    current_artifacts: int = 0
    max_download_bytes: int = 100 * 1024 * 1024
    current_download_bytes: int = 0


class SessionHandle(BaseModel):
    """顶层会话句柄"""
    session_id: str
    workflow_instance_id: str | None = None
    created_at: datetime
    last_active_at: datetime
    browser_config: dict[str, Any] = {}
    resource_quota: ResourceQuota = Field(default_factory=ResourceQuota)
    context_ids: list[str] = []


class BrowserContextHandle(BaseModel):
    """浏览器上下文句柄"""
    context_id: str
    session_id: str
    created_at: datetime
    page_ids: list[str] = []


class PageHandle(BaseModel):
    """页面句柄"""
    page_id: str
    context_id: str
    url: str = ""
    title: str = ""
    created_at: datetime


class ContextOptions(BaseModel):
    """Context 创建选项"""
    viewport_width: int = 1280
    viewport_height: int = 800
    user_agent: str | None = None
    extra_http_headers: dict[str, str] = {}
    storage_state: dict[str, Any] | None = None


class ContextSummary(BaseModel):
    """Context 状态摘要"""
    context_id: str
    page_count: int
    created_at: datetime


class PageSummary(BaseModel):
    """Page 状态摘要"""
    page_id: str
    url: str
    title: str
    idle_seconds: float


# ── 失败上下文 ────────────────────────────────────────────────────────

class FailureContext(BaseModel):
    """失败时产出的上下文快照"""
    url: str
    title: str
    error_code: BrowserErrorCode
    error_message: str
    completed_actions: list[ActionResult] = []
    last_page_snapshot: PageStateSnapshot | None = None
    error_stack_summary: str = ""

    def to_json(self) -> str:
        return self.model_dump_json()


# ── 录制模型 ──────────────────────────────────────────────────────────

class RecordingEntry(BaseModel):
    """单个操作的录制条目"""
    action: ActionPrimitive
    selector_resolution: SelectorResolution | None = None
    pre_snapshot: PageStateSnapshot | None = None
    post_snapshot: PageStateSnapshot | None = None
    result: ActionResult
    artifact_refs: list[str] = []


class RecordingMetadata(BaseModel):
    """录制元数据"""
    recorded_at: datetime
    target_url: str = ""
    browser_config: dict[str, Any] = {}
    session_id: str = ""


class Recording(BaseModel):
    """完整录制记录"""
    metadata: RecordingMetadata
    entries: list[RecordingEntry] = []


class PlaybackResult(BaseModel):
    """回放结果"""
    success: bool
    completed_entries: int
    total_entries: int
    failed_entry_index: int | None = None
    error: str | None = None


# ── 配置模型 ──────────────────────────────────────────────────────────

class BrowserAutomationConfig(BaseModel):
    """浏览器自动化执行器配置"""
    max_concurrent_sessions: int = Field(default=5, ge=1, le=20)
    max_pages_per_session: int = Field(default=10, ge=1, le=50)
    session_idle_timeout_seconds: int = Field(default=300, gt=0)
    default_navigation_timeout_ms: int = Field(default=30000, gt=0)
    default_action_timeout_ms: int = Field(default=10000, gt=0)
    viewport_width: int = Field(default=1280, gt=0)
    viewport_height: int = Field(default=800, gt=0)
    headless: bool = True
    # 资源配额
    max_artifacts_per_session: int = Field(default=50, gt=0)
    max_screenshot_size_bytes: int = Field(default=5 * 1024 * 1024, gt=0)
    max_download_size_bytes: int = Field(default=100 * 1024 * 1024, gt=0)
    download_dir_quota_bytes: int = Field(default=500 * 1024 * 1024, gt=0)
    recording_retention_count: int = Field(default=100, gt=0)


# ── 安全策略配置 ──────────────────────────────────────────────────────

class ActionPolicyConfig(BaseModel):
    """安全策略配置"""
    url_whitelist: list[str] = []
    url_blacklist: list[str] = []
    overrides: dict[str, SecurityLevel] = {}
    approval_timeout_seconds: int = Field(default=60, gt=0)
