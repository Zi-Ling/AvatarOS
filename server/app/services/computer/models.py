# app/services/computer/models.py
"""Computer Use Runtime — all data models."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Union

from pydantic import BaseModel, Field

from app.avatar.skills.schema import SkillInput, SkillOutput


# ── Enums ─────────────────────────────────────────────────────────────


class DominantLayout(str, Enum):
    DIALOG = "dialog"
    FORM = "form"
    LIST = "list"
    EDITOR = "editor"
    BROWSER = "browser"
    UNKNOWN = "unknown"


class ActionType(str, Enum):
    CLICK = "click"
    TYPE_TEXT = "type_text"
    HOTKEY = "hotkey"
    SCROLL = "scroll"
    WAIT = "wait"
    READ_SCREEN = "read_screen"


class ClickType(str, Enum):
    SINGLE = "single"
    DOUBLE = "double"
    RIGHT = "right"


class ScrollDirection(str, Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"


class FallbackStrategy(str, Enum):
    RETRY = "retry"
    RETRY_RELOCATE = "retry_relocate"
    UNDO_AND_RETRY = "undo_and_retry"
    SKIP = "skip"
    ABORT = "abort"


class VerificationStrategy(str, Enum):
    ELEMENT_APPEARED = "element_appeared"
    ELEMENT_DISAPPEARED = "element_disappeared"
    TEXT_CHANGED = "text_changed"
    TEXT_CONTAINS = "text_contains"
    WINDOW_TITLE_CHANGED = "window_title_changed"
    SCREENSHOT_DIFF = "screenshot_diff"
    STATE_HASH_CHANGED = "state_hash_changed"
    UIA_PROPERTY_CHANGED = "uia_property_changed"


class TransitionType(str, Enum):
    SUCCESS_TRANSITION = "success_transition"
    NO_CHANGE = "no_change"
    UNEXPECTED_TRANSITION = "unexpected_transition"
    UNKNOWN = "unknown"


class StuckType(str, Enum):
    ACTION_FAILED = "action_failed"
    STATE_UNCHANGED = "state_unchanged"
    UNEXPECTED_TRANSITION = "unexpected_transition"


class LocatorSource(str, Enum):
    UIA = "uia"
    OCR = "ocr"
    LLM_VISION = "llm_vision"


class OperationLevel(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    DANGEROUS = "dangerous"


class VerificationVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


class FormFieldType(str, Enum):
    TEXT = "text"
    SELECT = "select"
    CHECKBOX = "checkbox"


# ── Core state models ─────────────────────────────────────────────────


class VisibleElement(BaseModel):
    """可见 UI 元素摘要"""
    name: str = ""
    element_type: str = ""
    bbox: Optional[tuple[int, int, int, int]] = None
    text: str = ""
    is_enabled: bool = True
    is_focused: bool = False


class DialogInfo(BaseModel):
    """活跃对话框信息"""
    title: str = ""
    dialog_type: str = ""
    buttons: list[str] = Field(default_factory=list)
    message: str = ""


class GUIState(BaseModel):
    """屏幕状态结构化快照"""
    app_name: str
    window_title: str
    ui_signature: str = ""
    dominant_layout: DominantLayout = DominantLayout.UNKNOWN
    visible_elements: list[VisibleElement] = Field(default_factory=list)
    active_dialog: Optional[DialogInfo] = None
    loading_state: bool = False
    extracted_text: str = ""
    state_hash: str
    timestamp: float = Field(
        default_factory=lambda: datetime.now(timezone.utc).timestamp()
    )
    screenshot_artifact_id: Optional[str] = None
    vision_unavailable: bool = False

    @staticmethod
    def _normalize_elements_summary(elements: list[VisibleElement]) -> str:
        sorted_elems = sorted(elements, key=lambda e: (e.bbox or (0, 0, 0, 0)))
        return "|".join(f"{e.name}:{e.element_type}:{e.bbox}" for e in sorted_elems)

    @staticmethod
    def compute_hash(
        app_name: str,
        window_title: str,
        elements_summary: str,
        dominant_layout: str = "",
        dialog_title: str = "",
        ocr_text_prefix: str = "",
    ) -> str:
        content = (
            f"{app_name}|{window_title}|{dominant_layout}"
            f"|{dialog_title}|{elements_summary}|{ocr_text_prefix[:200]}"
        )
        return hashlib.sha256(content.encode()).hexdigest()[:16]


class OCRTextBlock(BaseModel):
    """OCR 文本块"""
    text: str
    bbox: tuple[int, int, int, int]
    confidence: float = 0.0


class UIAElement(BaseModel):
    """UIAutomation 控件元素"""
    name: str = ""
    control_type: str = ""
    bounding_rect: Optional[tuple[int, int, int, int]] = None
    is_enabled: bool = True
    is_visible: bool = True
    value: Optional[str] = None
    automation_id: str = ""
    children_count: int = 0


class AnalysisResult(BaseModel):
    """ScreenAnalyzer 分析结果"""
    gui_state: GUIState
    screenshot_b64: str
    image_hash: str
    llm_usage: Optional[dict] = None


class ObservationBundle(BaseModel):
    """Observe 阶段一次性产出的完整观测包"""
    screenshot_b64: str
    image_hash: str
    gui_state: GUIState
    ocr_blocks: list[OCRTextBlock] = Field(default_factory=list)
    uia_elements: list[UIAElement] = Field(default_factory=list)
    timestamp: float = Field(
        default_factory=lambda: datetime.now(timezone.utc).timestamp()
    )
    foreground_window_title: str = ""
    foreground_hwnd: Optional[int] = None


# ── Locator models ────────────────────────────────────────────────────


class LocatorCandidate(BaseModel):
    """单源定位候选"""
    source: LocatorSource
    bbox: tuple[int, int, int, int]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    element_info: Optional[dict[str, Any]] = None


class LocatorResult(BaseModel):
    """定位融合结果"""
    success: bool
    chosen_candidate: Optional[LocatorCandidate] = None
    all_candidates: list[LocatorCandidate] = Field(default_factory=list)
    fusion_confidence: float = 0.0
    decision_reason: str = ""
    click_point: Optional[tuple[int, int]] = None


# ── Typed verification params ─────────────────────────────────────────


class ElementAppearedParams(BaseModel):
    element_description: str
    element_type: Optional[str] = None


class ElementDisappearedParams(BaseModel):
    element_description: str


class TextChangedParams(BaseModel):
    region_description: str
    expected_old_text: Optional[str] = None


class TextContainsParams(BaseModel):
    expected_text: str
    region_description: Optional[str] = None


class WindowTitleChangedParams(BaseModel):
    expected_title_contains: str


class ScreenshotDiffParams(BaseModel):
    diff_threshold: float = 0.05
    region: Optional[tuple[int, int, int, int]] = None


class StateHashChangedParams(BaseModel):
    pass


class UIAPropertyChangedParams(BaseModel):
    element_name: str
    property_name: str
    expected_value: Optional[str] = None


VerificationParams = Union[
    ElementAppearedParams,
    ElementDisappearedParams,
    TextChangedParams,
    TextContainsParams,
    WindowTitleChangedParams,
    ScreenshotDiffParams,
    StateHashChangedParams,
    UIAPropertyChangedParams,
]


# ── Action models ─────────────────────────────────────────────────────


class ActionTarget(BaseModel):
    description: str
    window_title_hint: Optional[str] = None


class ActionParams(BaseModel):
    text: Optional[str] = None
    keys: Optional[list[str]] = None
    direction: Optional[ScrollDirection] = None
    amount: int = 3
    timeout: int = 5
    click_type: ClickType = ClickType.SINGLE
    appear: bool = True


class ActionPrecondition(BaseModel):
    window_title_contains: Optional[str] = None
    element_visible: Optional[bool] = None


class ActionVerification(BaseModel):
    strategy: VerificationStrategy
    params: VerificationParams


class ActionFallback(BaseModel):
    on_fail: FallbackStrategy = FallbackStrategy.RETRY


class ActionPlan(BaseModel):
    """结构化动作计划 — LLM Think 阶段输出"""
    action: ActionType
    target: ActionTarget
    params: ActionParams = Field(default_factory=ActionParams)
    precondition: Optional[ActionPrecondition] = None
    verification: Optional[ActionVerification] = None
    fallback: ActionFallback = Field(default_factory=ActionFallback)
    decision_summary: str = ""
    evidence_basis: list[str] = Field(default_factory=list)


# ── Result models ─────────────────────────────────────────────────────


class ActionResult(BaseModel):
    success: bool
    action_type: ActionType
    target_coords: Optional[tuple[int, int]] = None
    locator_evidence: Optional[LocatorResult] = None
    error: Optional[str] = None
    duration_ms: float = 0.0


class VerificationResult(BaseModel):
    verdict: VerificationVerdict
    strategy: VerificationStrategy
    evidence: dict[str, Any] = Field(default_factory=dict)
    details: str = ""


class TransitionVerdict(BaseModel):
    verdict_type: TransitionType
    confidence: float = 0.0
    reason: str = ""


class StuckCheckResult(BaseModel):
    is_stuck: bool = False
    stuck_type: Optional[StuckType] = None
    recommendation: str = ""


class SafetyCheckResult(BaseModel):
    allowed: bool
    reason: str = ""
    requires_approval: bool = False
    approval_request_id: Optional[str] = None
    operation_level: OperationLevel = OperationLevel.READ


# ── Session state ─────────────────────────────────────────────────────


class ActionHistoryEntry(BaseModel):
    step_index: int
    action_type: ActionType
    target_description: str
    success: bool
    verdict_type: Optional[TransitionType] = None
    timestamp: float = 0.0


class ComputerUseSessionState(BaseModel):
    """Computer Use 专属 Session 状态"""
    session_id: str
    goal: str
    current_step_index: int = 0
    last_screenshot_artifact_id: Optional[str] = None
    last_state_hash: Optional[str] = None
    last_analysis: Optional[GUIState] = None
    last_locator_result: Optional[LocatorResult] = None
    failure_streak: int = 0
    unchanged_streak: int = 0
    unexpected_streak: int = 0
    retry_count: int = 0
    active_window: Optional[str] = None
    focus_lost_count: int = 0
    approval_pending: bool = False
    stuck_reason: Optional[str] = None
    action_history: list[ActionHistoryEntry] = Field(default_factory=list)
    started_at: float = Field(
        default_factory=lambda: datetime.now(timezone.utc).timestamp()
    )
    max_steps: int = 50
    timeout_seconds: int = 600
    # Recovery & tracking fields
    pending_action_plan: Optional[ActionPlan] = None
    last_verification_result: Optional[VerificationResult] = None
    pending_approval_request_id: Optional[str] = None
    last_foreground_window: Optional[str] = None
    last_observe_timestamp: Optional[float] = None
    replan_count: int = 0
    llm_call_count: int = 0


# ── Final result models ───────────────────────────────────────────────


class EvidenceEntry(BaseModel):
    step_index: int
    screenshot_artifact_id: Optional[str] = None
    action_type: ActionType
    target_description: str
    locator_source: Optional[LocatorSource] = None
    locator_confidence: float = 0.0
    verification_verdict: Optional[VerificationVerdict] = None
    transition_type: Optional[TransitionType] = None


class OTAVResult(BaseModel):
    success: bool
    result_summary: str = ""
    steps_taken: int = 0
    evidence_chain: list[EvidenceEntry] = Field(default_factory=list)
    failure_reason: Optional[str] = None
    final_gui_state: Optional[GUIState] = None
    total_duration_ms: float = 0.0
    llm_calls: int = 0


class ComputerUseResult(BaseModel):
    success: bool
    result_summary: str = ""
    steps_taken: int = 0
    evidence_chain: list[EvidenceEntry] = Field(default_factory=list)
    failure_reason: Optional[str] = None
    session_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


# ── Config ────────────────────────────────────────────────────────────


class ComputerUseConfig(BaseModel):
    max_steps: int = 50
    max_duration_seconds: int = 600
    observe_freshness_seconds: float = 5.0
    post_action_wait: float = 1.0
    max_wait_timeout: float = 30.0
    min_action_interval: float = 0.1
    confidence_threshold: float = 0.3
    max_unchanged_streak: int = 3
    max_failed_streak: int = 3
    max_unexpected_streak: int = 2
    max_retry_per_step: int = 3
    screenshot_diff_threshold: float = 0.05
    cache_ttl: float = 3.0
    # LLM budget
    max_llm_calls_per_step: int = 3
    max_total_llm_calls: int = 100
    vision_budget_per_step: int = 2
    # Progress report
    progress_report_interval: int = 3


class DPIInfo(BaseModel):
    """显示器 DPI 缩放信息"""
    scale_factor: float = 1.0
    physical_size: tuple[int, int] = (1920, 1080)
    logical_size: tuple[int, int] = (1920, 1080)


class ProgressReport(BaseModel):
    session_id: str
    current_step: int
    max_steps: int
    last_action_summary: str = ""
    estimated_progress_pct: float = 0.0
    llm_calls_used: int = 0
    llm_calls_budget: int = 100
    elapsed_seconds: float = 0.0


class GoalJudgeResult(BaseModel):
    goal_achieved: bool = False
    confidence: float = 0.0
    reason: str = ""
    remaining_steps_hint: Optional[str] = None


# ── Wait models ───────────────────────────────────────────────────────


class WaitCondition(BaseModel):
    description: str
    appear: bool = True
    timeout: float = 10.0
    poll_interval: float = 0.5


class WaitResult(BaseModel):
    condition_met: bool = False
    elapsed_seconds: float = 0.0
    final_state: Optional[GUIState] = None


# ── Locator scoring config ────────────────────────────────────────────


class LocatorScoringWeights(BaseModel):
    source_prior: float = 0.3
    text_similarity: float = 0.25
    visibility_state: float = 0.15
    window_consistency: float = 0.15
    history_proximity: float = 0.15


# ── Skill I/O models ─────────────────────────────────────────────────


class ComputerUseInput(SkillInput):
    goal: str = Field(..., description="自然语言目标描述")
    max_steps: int = Field(50, description="最大 OTAV 循环步数")
    timeout: int = Field(600, description="最大执行时间（秒）")


class ComputerUseOutput(SkillOutput):
    result_summary: str = ""
    steps_taken: int = 0
    evidence_chain: list[EvidenceEntry] = Field(default_factory=list)
    failure_reason: Optional[str] = None


class ReadScreenInput(SkillInput):
    roi: Optional[tuple[int, int, int, int]] = Field(
        None, description="感兴趣区域 (left, top, w, h)"
    )
    context_hint: Optional[str] = Field(None, description="上下文提示")


class ReadScreenOutput(SkillOutput):
    gui_state: Optional[GUIState] = None
    screenshot_artifact_id: Optional[str] = None


class ClickElementInput(SkillInput):
    description: str = Field(..., description="要点击的元素描述")
    click_type: ClickType = Field(ClickType.SINGLE, description="点击类型")


class ClickElementOutput(SkillOutput):
    clicked_coords: Optional[tuple[int, int]] = None
    locator_source: Optional[LocatorSource] = None
    confidence: float = 0.0


class TypeTextInput(SkillInput):
    target_description: str = Field(..., description="目标输入框描述")
    text: str = Field(..., description="要输入的文本")


class TypeTextOutput(SkillOutput):
    typed_text: str = ""
    target_coords: Optional[tuple[int, int]] = None


class WaitForInput(SkillInput):
    description: str = Field(..., description="等待的元素描述")
    timeout: int = Field(10, description="超时时间（秒）")
    appear: bool = Field(True, description="True=等待出现, False=等待消失")


class WaitForOutput(SkillOutput):
    found: bool = False
    elapsed_seconds: float = 0.0


class FormFieldAction(BaseModel):
    field_description: str = Field(..., description="字段描述（用于定位）")
    value: str = Field(..., description="要填入的值")
    field_type: FormFieldType = Field(FormFieldType.TEXT, description="字段类型")


class FillFormInput(SkillInput):
    fields: list[FormFieldAction] = Field(
        ..., description="按顺序执行的字段操作列表"
    )


class FillFormOutput(SkillOutput):
    filled_fields: list[str] = Field(default_factory=list)
    failed_fields: list[str] = Field(default_factory=list)
