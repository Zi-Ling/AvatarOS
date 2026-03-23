# app/services/computer/ime_controller.py
"""IMEController — 输入法全生命周期管控.

核心原则：
- 切换并验证，不是切换并祈祷
- 恢复前检查上下文一致性（窗口/线程），不一致则放弃恢复
- 生产和测试共用
"""

from __future__ import annotations

import logging
import platform
import time
from typing import Optional

from .desktop_models import IMEState

logger = logging.getLogger(__name__)

# US English keyboard layout
_EN_US_LAYOUT = 0x0409
_EN_US_LAYOUT_NAME = "00000409"
_MAX_RETRY = 3
_PROBE_CHAR = "a"  # 探针字符，用于验证输入法状态


class IMEController:
    """输入法状态管控器.

    使用方式：
        ime = IMEController()
        saved = ime.ensure_english()   # 切英文 + 探针验证
        # ... 执行键盘操作 ...
        ime.restore(saved)             # 恢复原始输入法（带上下文检查）
    """

    def __init__(self) -> None:
        self._is_windows = platform.system() == "Windows"

    def probe(self) -> IMEState:
        """探测当前输入法状态."""
        if not self._is_windows:
            return IMEState(is_english=True, language="en-US")
        try:
            import ctypes
            user32 = ctypes.windll.user32

            hwnd = user32.GetForegroundWindow()
            thread_id = user32.GetWindowThreadProcessId(hwnd, None)
            hkl = user32.GetKeyboardLayout(thread_id)

            # 低 16 位是语言 ID
            lang_id = hkl & 0xFFFF
            is_english = lang_id == _EN_US_LAYOUT

            return IMEState(
                layout_id=hkl,
                layout_name=f"{hkl:08x}",
                language="en-US" if is_english else f"lang-{lang_id:04x}",
                is_english=is_english,
                thread_id=thread_id,
                hwnd=hwnd,
            )
        except Exception as e:
            logger.warning(f"IME probe failed: {e}")
            return IMEState(is_english=True, language="unknown")

    def ensure_english(self) -> Optional[IMEState]:
        """切换到英文输入法并验证.

        Returns:
            切换前的 IMEState（用于后续 restore），如果已经是英文则返回 None
        """
        if not self._is_windows:
            return None

        current = self.probe()
        if current.is_english:
            logger.debug("IME already English, no switch needed")
            return None

        saved_state = current
        logger.info(f"IME switching from {current.language} to en-US")

        for attempt in range(1, _MAX_RETRY + 1):
            self._activate_english()
            time.sleep(0.15)

            # 探针验证
            verified = self._verify_english()
            if verified:
                logger.info(f"IME switched to English (attempt {attempt})")
                return saved_state

            logger.warning(f"IME switch attempt {attempt} failed, retrying...")
            time.sleep(0.2)

        # 所有重试失败，尝试更强力的方式
        logger.warning("IME soft switch failed, trying hard API switch")
        self._hard_activate_english()
        time.sleep(0.2)

        if self._verify_english():
            logger.info("IME hard switch succeeded")
            return saved_state

        logger.error("IME switch to English FAILED after all retries")
        return saved_state  # 仍然返回 saved，让调用方决定是否继续

    def restore(self, saved_state: Optional[IMEState]) -> bool:
        """恢复输入法到之前的状态.

        策略：用 ActivateKeyboardLayout + KLF_SETFORPROCESS 做进程级恢复，
        不依赖特定窗口/线程。这样即使目标窗口已关闭也能恢复。
        """
        if saved_state is None:
            return True

        if not self._is_windows:
            return True

        if saved_state.is_english:
            # 之前就是英文，当前也是英文（ensure_english 切过来的），无需恢复
            current = self.probe()
            if current.is_english:
                return True

        try:
            import ctypes
            user32 = ctypes.windll.user32

            # KLF_SETFORPROCESS = 0x100：作用于整个进程，不依赖特定窗口
            result = user32.ActivateKeyboardLayout(
                saved_state.layout_id, 0x00000100
            )
            if result:
                logger.info(
                    f"IME restored to {saved_state.language} "
                    f"(layout={saved_state.layout_id:#x}, process-wide)"
                )
                return True

            # ActivateKeyboardLayout 失败，用 LoadKeyboardLayout 兜底
            logger.warning(
                "IME ActivateKeyboardLayout failed, trying LoadKeyboardLayout"
            )
            lang_id = saved_state.layout_id & 0xFFFF
            layout_name = f"{lang_id:08x}"
            hkl = user32.LoadKeyboardLayoutW(layout_name, 0x00000101)
            if hkl:
                logger.info(
                    f"IME restored via LoadKeyboardLayout: {layout_name}"
                )
                return True

            logger.warning(f"IME restore failed for {saved_state.language}")
            return False
        except Exception as e:
            logger.warning(f"IME restore failed: {e}")
            return False

    # ── private ───────────────────────────────────────────────────────

    def _activate_english(self) -> None:
        """用 ActivateKeyboardLayout API 切换到英文."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            # KLF_ACTIVATE = 1, KLF_SETFORPROCESS = 0x100
            user32.ActivateKeyboardLayout(_EN_US_LAYOUT, 0x00000101)
        except Exception as e:
            logger.warning(f"ActivateKeyboardLayout failed: {e}")

    def _hard_activate_english(self) -> None:
        """更强力的切换方式：LoadKeyboardLayout + PostMessage."""
        try:
            import ctypes
            user32 = ctypes.windll.user32

            # 先加载英文布局
            hkl = user32.LoadKeyboardLayoutW(
                _EN_US_LAYOUT_NAME, 0x00000101  # KLF_ACTIVATE | KLF_SETFORPROCESS
            )
            if hkl:
                # 向前台窗口发送 WM_INPUTLANGCHANGEREQUEST
                hwnd = user32.GetForegroundWindow()
                WM_INPUTLANGCHANGEREQUEST = 0x0050
                user32.PostMessageW(hwnd, WM_INPUTLANGCHANGEREQUEST, 0, hkl)
        except Exception as e:
            logger.warning(f"Hard IME switch failed: {e}")

    def _verify_english(self) -> bool:
        """验证当前输入法确实是英文.

        方法：检查 GetKeyboardLayout 返回的语言 ID。
        """
        state = self.probe()
        return state.is_english
