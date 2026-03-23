# app/services/computer/interrupt_detector.py
"""InterruptDetector — 用户干预检测.

检测：
- 前台窗口被切走（焦点丢失）
- 目标窗口被关闭
- 鼠标被用户抢占（位置突变）
- 弹窗打断（新窗口出现）
- 输入法被切换
"""

from __future__ import annotations

import logging
import platform
import time
from typing import Optional

from .desktop_models import InterruptEvent, InterruptType, IMEState

logger = logging.getLogger(__name__)


class InterruptDetector:
    """用户干预检测器.

    使用方式：
        detector = InterruptDetector()
        detector.set_target(hwnd=12345, title="记事本")
        # ... 执行操作 ...
        event = detector.check()
        if event:
            handle_interrupt(event)
    """

    def __init__(self) -> None:
        self._is_windows = platform.system() == "Windows"
        self._target_hwnd: int = 0
        self._target_title: str = ""
        self._last_mouse_pos: Optional[tuple[int, int]] = None
        self._last_mouse_time: float = 0.0
        self._last_ime_state: Optional[IMEState] = None
        # 鼠标突变阈值：200px 内 0.1 秒
        self._mouse_jump_threshold = 200
        self._mouse_time_threshold = 0.1

    def set_target(
        self,
        hwnd: int = 0,
        title: str = "",
        ime_state: Optional[IMEState] = None,
    ) -> None:
        """设置监控目标."""
        self._target_hwnd = hwnd
        self._target_title = title
        self._last_ime_state = ime_state
        self._last_mouse_pos = None
        self._last_mouse_time = 0.0

    def check(self) -> Optional[InterruptEvent]:
        """执行一次干预检测，返回检测到的干预事件或 None."""
        if not self._is_windows:
            return None

        # 检测优先级：窗口关闭 > 焦点丢失 > 弹窗 > 鼠标抢占 > 输入法变化
        event = self._check_window_closed()
        if event:
            return event

        event = self._check_focus_lost()
        if event:
            return event

        event = self._check_popup()
        if event:
            return event

        event = self._check_mouse_hijacked()
        if event:
            return event

        event = self._check_ime_changed()
        if event:
            return event

        return None

    def update_mouse_position(self, x: int, y: int) -> None:
        """更新已知的鼠标位置（操作后调用）."""
        self._last_mouse_pos = (x, y)
        self._last_mouse_time = time.time()

    # ── private checks ────────────────────────────────────────────────

    def _get_foreground(self) -> tuple[int, str]:
        """获取当前前台窗口 hwnd 和标题."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return (hwnd, "")
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            return (hwnd, buf.value)
        except Exception:
            return (0, "")

    def _is_window_alive(self, hwnd: int) -> bool:
        """检查窗口是否仍然存在."""
        if hwnd == 0:
            return False
        try:
            import ctypes
            return bool(ctypes.windll.user32.IsWindow(hwnd))
        except Exception:
            return False

    def _check_window_closed(self) -> Optional[InterruptEvent]:
        if self._target_hwnd == 0:
            return None
        if not self._is_window_alive(self._target_hwnd):
            return InterruptEvent(
                interrupt_type=InterruptType.WINDOW_CLOSED,
                details=f"Target window closed: {self._target_title}",
                expected_hwnd=self._target_hwnd,
                expected_title=self._target_title,
            )
        return None

    def _check_focus_lost(self) -> Optional[InterruptEvent]:
        if self._target_hwnd == 0:
            return None
        actual_hwnd, actual_title = self._get_foreground()
        if actual_hwnd != self._target_hwnd:
            return InterruptEvent(
                interrupt_type=InterruptType.FOCUS_LOST,
                details=f"Focus lost: expected '{self._target_title}', got '{actual_title}'",
                expected_hwnd=self._target_hwnd,
                actual_hwnd=actual_hwnd,
                expected_title=self._target_title,
                actual_title=actual_title,
            )
        return None

    def _check_popup(self) -> Optional[InterruptEvent]:
        """检测是否有新弹窗覆盖了目标窗口."""
        if self._target_hwnd == 0:
            return None
        actual_hwnd, actual_title = self._get_foreground()
        if actual_hwnd == self._target_hwnd:
            return None
        # 如果前台窗口不是目标，且是一个对话框类型的窗口
        try:
            import ctypes
            user32 = ctypes.windll.user32
            # 检查窗口样式是否是对话框 (WS_DLGFRAME)
            GWL_STYLE = -16
            style = user32.GetWindowLongW(actual_hwnd, GWL_STYLE)
            WS_DLGFRAME = 0x00400000
            WS_POPUP = 0x80000000
            if style & (WS_DLGFRAME | WS_POPUP):
                return InterruptEvent(
                    interrupt_type=InterruptType.POPUP_DETECTED,
                    details=f"Popup detected: '{actual_title}'",
                    expected_hwnd=self._target_hwnd,
                    actual_hwnd=actual_hwnd,
                    expected_title=self._target_title,
                    actual_title=actual_title,
                )
        except Exception:
            pass
        return None

    def _check_mouse_hijacked(self) -> Optional[InterruptEvent]:
        if self._last_mouse_pos is None:
            return None
        try:
            import pyautogui
            current = pyautogui.position()
            elapsed = time.time() - self._last_mouse_time
            if elapsed > self._mouse_time_threshold:
                return None  # 太久了，不算突变
            dx = abs(current[0] - self._last_mouse_pos[0])
            dy = abs(current[1] - self._last_mouse_pos[1])
            if dx + dy > self._mouse_jump_threshold:
                return InterruptEvent(
                    interrupt_type=InterruptType.MOUSE_HIJACKED,
                    details=(
                        f"Mouse jumped from {self._last_mouse_pos} to "
                        f"{current} in {elapsed:.3f}s"
                    ),
                )
        except Exception:
            pass
        return None

    def _check_ime_changed(self) -> Optional[InterruptEvent]:
        if self._last_ime_state is None:
            return None
        try:
            from .ime_controller import IMEController
            ime = IMEController()
            current = ime.probe()
            if current.layout_id != self._last_ime_state.layout_id:
                event = InterruptEvent(
                    interrupt_type=InterruptType.IME_CHANGED,
                    details=(
                        f"IME changed from {self._last_ime_state.language} "
                        f"to {current.language}"
                    ),
                )
                self._last_ime_state = current
                return event
        except Exception:
            pass
        return None
