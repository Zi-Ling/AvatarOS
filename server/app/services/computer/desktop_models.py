# app/services/computer/desktop_models.py
"""桌面环境管理 — 数据模型 & 审计 Schema."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── 输入法状态 ────────────────────────────────────────────────────────


class IMEState(BaseModel):
    """输入法快照"""
    layout_id: int = 0          # HKL (keyboard layout handle)
    layout_name: str = ""       # e.g. "00000409" (US English)
    language: str = ""          # e.g. "en-US", "zh-CN"
    is_english: bool = False
    thread_id: int = 0          # 关联的线程 ID
    hwnd: int = 0               # 关联的窗口句柄


# ── 桌面环境快照 ──────────────────────────────────────────────────────


class DesktopSnapshot(BaseModel):
    """桌面环境状态快照 — 用于 probe/restore"""
    ime_state: Optional[IMEState] = None
    foreground_hwnd: int = 0
    foreground_title: str = ""
    screen_width: int = 0
    screen_height: int = 0
    dpi_scale: float = 1.0
    clipboard_text: str = ""
    timestamp: float = Field(
        default_factory=lambda: datetime.now(timezone.utc).timestamp()
    )


# ── 应用会话 ──────────────────────────────────────────────────────────


class AppSession(BaseModel):
    """确定性启动的应用会话"""
    pid: int = 0
    hwnd: int = 0
    window_title: str = ""
    app_name: str = ""
    temp_file: Optional[str] = None   # 启动时创建的临时文件
    launched_at: float = Field(
        default_factory=lambda: datetime.now(timezone.utc).timestamp()
    )


# ── 用户干预检测 ──────────────────────────────────────────────────────


class InterruptType(str, Enum):
    """用户干预类型"""
    FOCUS_LOST = "focus_lost"           # 目标窗口失焦
    WINDOW_CLOSED = "window_closed"     # 目标窗口被关闭
    MOUSE_HIJACKED = "mouse_hijacked"   # 鼠标被用户抢占
    POPUP_DETECTED = "popup_detected"   # 弹窗打断
    IME_CHANGED = "ime_changed"         # 输入法被切换


class InterruptEvent(BaseModel):
    """干预事件"""
    interrupt_type: InterruptType
    timestamp: float = Field(
        default_factory=lambda: datetime.now(timezone.utc).timestamp()
    )
    details: str = ""
    expected_hwnd: int = 0
    actual_hwnd: int = 0
    expected_title: str = ""
    actual_title: str = ""


# ── 审计 Schema ───────────────────────────────────────────────────────


class LocatorStrategy(str, Enum):
    """定位策略"""
    UIA = "uia"
    OCR = "ocr"
    STRUCTURAL_ANCHOR = "structural_anchor"  # 窗口/控件结构锚点
    IMAGE_TEMPLATE = "image_template"
    COORDINATE = "coordinate"
    KEYBOARD_SEQUENCE = "keyboard_sequence"


class AuditStep(BaseModel):
    """单步操作审计记录 — 固定 schema"""
    step_id: int
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    # 环境上下文
    active_window_title: str = ""
    active_window_hwnd: int = 0
    ime_state: str = ""                 # "en-US" / "zh-CN"
    # 定位
    locator_strategy: Optional[LocatorStrategy] = None
    locator_evidence: Optional[dict[str, Any]] = None
    locator_target: str = ""            # 目标描述
    locator_confidence: float = 0.0
    # 动作
    action: str = ""                    # "click", "type", "hotkey", etc.
    action_params: dict[str, Any] = Field(default_factory=dict)
    target_coords: Optional[tuple[int, int]] = None
    # 验证
    pre_state: Optional[dict[str, Any]] = None   # 控制面断言
    post_state: Optional[dict[str, Any]] = None
    verification_passed: Optional[bool] = None
    verification_details: str = ""
    # 结果
    success: bool = False
    error: Optional[str] = None
    duration_ms: float = 0.0
    # 截图
    screenshot_before: Optional[str] = None  # artifact ID 或路径
    screenshot_after: Optional[str] = None
    # 干预
    interrupt_detected: Optional[InterruptEvent] = None


class AuditSession(BaseModel):
    """完整审计会话"""
    session_id: str
    goal: str = ""
    started_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    ended_at: Optional[str] = None
    steps: list[AuditStep] = Field(default_factory=list)
    total_steps: int = 0
    success: bool = False
    failure_reason: Optional[str] = None
    environment: Optional[DesktopSnapshot] = None


# ── UIA 控件状态快照 ──────────────────────────────────────────────────


class ControlSnapshot(BaseModel):
    """UIA 控件结构化状态快照 — 比 UIAElement 更丰富"""
    automation_id: str = ""
    name: str = ""
    class_name: str = ""
    control_type: str = ""
    bounding_rect: Optional[tuple[int, int, int, int]] = None
    is_enabled: bool = True
    is_offscreen: bool = False
    has_keyboard_focus: bool = False
    # Value/Text pattern 摘要
    value: Optional[str] = None
    text_content: Optional[str] = None
    # 层级信息
    depth: int = 0
    children_count: int = 0
    parent_name: str = ""
