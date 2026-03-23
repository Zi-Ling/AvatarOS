# app/services/computer/desktop_env.py
"""DesktopEnv — 桌面环境状态管理器.

语义分离：
- probe()     — 探测当前环境状态（生产+测试）
- stabilize() — 尽量稳定化环境（生产：不破坏用户状态）
- restore()   — 恢复到之前的快照（生产：有条件恢复）
- reset()     — 强制重置到干净状态（仅测试使用）
"""

from __future__ import annotations

import logging
import platform
from typing import Optional

from .desktop_models import DesktopSnapshot, IMEState
from .ime_controller import IMEController
from .interrupt_detector import InterruptDetector

logger = logging.getLogger(__name__)


class DesktopEnv:
    """桌面环境管理器 — 生产和测试共用."""

    def __init__(self) -> None:
        self._is_windows = platform.system() == "Windows"
        self.ime = IMEController()
        self.interrupt_detector = InterruptDetector()
        self._snapshot: Optional[DesktopSnapshot] = None

    def probe(self) -> DesktopSnapshot:
        """探测当前桌面环境状态."""
        ime_state = self.ime.probe()
        fg_hwnd, fg_title = self._get_foreground()
        sw, sh = self._get_screen_size()
        dpi = self._get_dpi_scale()
        clipboard = self._get_clipboard()

        snap = DesktopSnapshot(
            ime_state=ime_state,
            foreground_hwnd=fg_hwnd,
            foreground_title=fg_title,
            screen_width=sw,
            screen_height=sh,
            dpi_scale=dpi,
            clipboard_text=clipboard[:200] if clipboard else "",
        )
        logger.debug(
            f"Desktop probe: {fg_title} ({sw}x{sh} @{dpi}x) "
            f"IME={ime_state.language}"
        )
        return snap

    def snapshot(self) -> DesktopSnapshot:
        """保存当前环境快照（用于后续 restore）."""
        self._snapshot = self.probe()
        return self._snapshot

    def stabilize(self) -> DesktopSnapshot:
        """稳定化环境（生产模式）.

        - 切换输入法到英文（不破坏用户其他状态）
        - 返回稳定化后的环境快照
        """
        snap = self.probe()
        # 只做输入法稳定化，不清剪贴板、不杀进程
        self.ime.ensure_english()
        return self.probe()

    def restore(self, snap: Optional[DesktopSnapshot] = None) -> bool:
        """恢复到之前的快照（生产模式，有条件恢复）.

        只恢复输入法，且仅在上下文一致时恢复。
        """
        target = snap or self._snapshot
        if target is None:
            return True

        restored = True
        # 恢复输入法
        if target.ime_state:
            if not self.ime.restore(target.ime_state):
                restored = False

        return restored

    def reset(self) -> DesktopSnapshot:
        """强制重置到干净状态（仅测试使用）.

        - 切英文输入法
        - 清空剪贴板
        - 不杀进程（由 AppLauncher 管理）
        """
        # 切英文
        self.ime.ensure_english()

        # 清剪贴板
        self._clear_clipboard()

        return self.probe()

    # ── private helpers ───────────────────────────────────────────────

    def _get_foreground(self) -> tuple[int, str]:
        if not self._is_windows:
            return (0, "")
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

    def _get_screen_size(self) -> tuple[int, int]:
        try:
            import pyautogui
            return pyautogui.size()
        except Exception:
            return (1920, 1080)

    def _get_dpi_scale(self) -> float:
        if not self._is_windows:
            return 1.0
        try:
            import ctypes
            return ctypes.windll.user32.GetDpiForSystem() / 96.0
        except Exception:
            return 1.0

    def _get_clipboard(self) -> str:
        try:
            import pyperclip
            return pyperclip.paste() or ""
        except Exception:
            return ""

    def _clear_clipboard(self) -> None:
        try:
            import pyperclip
            pyperclip.copy("")
        except Exception:
            pass
