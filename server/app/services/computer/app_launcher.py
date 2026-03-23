# app/services/computer/app_launcher.py
"""AppLauncher — 确定性应用启动器.

设计原则：
- 杀旧进程 → 创建空临时文件 → 带路径启动 → 等待窗口 → 验证标题 → 验证可交互
- 第一版聚焦 Win32 文本类应用（记事本、计算器等），可扩展
- 返回 AppSession 对象，测试结束自动清理
"""

from __future__ import annotations

import glob
import logging
import os
import platform
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from .desktop_models import AppSession

logger = logging.getLogger(__name__)

# 已知应用的进程名映射
_KNOWN_APPS: dict[str, list[str]] = {
    "notepad": ["notepad.exe"],
    "calc": ["Calculator.exe", "CalculatorApp.exe", "calc.exe"],
    "calculator": ["Calculator.exe", "CalculatorApp.exe", "calc.exe"],
}


def _get_notepad_tabstate_dirs() -> list[Path]:
    """获取 Win11 新版记事本的 TabState 目录列表（延迟求值）."""
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if not local_app_data:
        return []
    pattern = os.path.join(
        local_app_data,
        "Packages",
        "Microsoft.WindowsNotepad_*",
        "LocalState",
        "TabState",
    )
    return [Path(p) for p in glob.glob(pattern) if Path(p).is_dir()]


class AppLauncher:
    """确定性应用启动器."""

    def __init__(self) -> None:
        self._is_windows = platform.system() == "Windows"
        self._sessions: list[AppSession] = []

    def launch(
        self,
        app_name: str,
        *,
        kill_existing: bool = True,
        temp_file_ext: str = ".txt",
        use_temp_file: bool = True,
        args: Optional[list[str]] = None,
        wait_seconds: float = 2.0,
        expected_title_fragment: Optional[str] = None,
    ) -> AppSession:
        """确定性启动应用.

        Args:
            app_name: 应用名称或路径 (e.g. "notepad", "calc")
            kill_existing: 是否先杀掉已有进程
            temp_file_ext: 临时文件扩展名
            use_temp_file: 是否创建临时文件并带路径启动
            args: 额外命令行参数
            wait_seconds: 等待窗口出现的时间
            expected_title_fragment: 预期窗口标题片段（用于验证）
        """
        if not self._is_windows:
            raise RuntimeError("AppLauncher only supports Windows")

        # 1. 杀旧进程
        if kill_existing:
            self._kill_app(app_name)
            time.sleep(0.5)
            # Win11 新版记事本：清理 TabState 防止会话恢复
            self._clear_app_state(app_name)

        # 2. 创建临时文件（避免恢复旧文件）
        temp_path: Optional[str] = None
        if use_temp_file:
            fd, temp_path = tempfile.mkstemp(
                suffix=temp_file_ext, prefix=f"ia_test_{app_name}_"
            )
            os.close(fd)

        # 3. 启动应用
        cmd_args = [app_name]
        if temp_path:
            cmd_args.append(temp_path)
        if args:
            cmd_args.extend(args)

        logger.info(f"Launching: {' '.join(cmd_args)}")
        proc = subprocess.Popen(cmd_args, shell=True)
        time.sleep(wait_seconds)

        # 4. 查找窗口
        hwnd, title = self._find_window(
            app_name, expected_title_fragment, temp_path
        )

        # 5. 验证窗口存在
        if hwnd == 0:
            logger.warning(
                f"Window not found for {app_name}, "
                f"proceeding with pid={proc.pid}"
            )

        # 6. 聚焦窗口
        if hwnd:
            self._focus_window(hwnd)

        session = AppSession(
            pid=proc.pid,
            hwnd=hwnd,
            window_title=title,
            app_name=app_name,
            temp_file=temp_path,
        )
        self._sessions.append(session)
        logger.info(
            f"App launched: {app_name} pid={proc.pid} "
            f"hwnd={hwnd} title='{title}'"
        )
        return session

    def cleanup(self, session: Optional[AppSession] = None) -> None:
        """清理应用会话（关闭进程 + 删除临时文件）."""
        sessions = [session] if session else list(self._sessions)
        for s in sessions:
            self._kill_app(s.app_name)
            if s.temp_file:
                try:
                    Path(s.temp_file).unlink(missing_ok=True)
                except Exception:
                    pass
            if s in self._sessions:
                self._sessions.remove(s)

    def cleanup_all(self) -> None:
        """清理所有会话."""
        for s in list(self._sessions):
            self.cleanup(s)

    # ── private ───────────────────────────────────────────────────────

    def _kill_app(self, app_name: str) -> None:
        """杀掉应用的所有进程."""
        process_names = _KNOWN_APPS.get(
            app_name.lower().replace(".exe", ""),
            [f"{app_name}.exe" if not app_name.endswith(".exe") else app_name],
        )
        for pname in process_names:
            try:
                subprocess.run(
                    f"taskkill /f /im {pname}",
                    shell=True, capture_output=True, timeout=5,
                )
            except Exception:
                pass

    def _clear_app_state(self, app_name: str) -> None:
        """清理应用的会话恢复状态（app-specific）.

        Win11 新版记事本会在 TabState 目录保存会话数据，
        杀掉进程后下次启动仍会恢复之前的 Tab 页和文件。
        必须在启动前清理这些文件才能获得确定性起始状态。
        """
        app_lower = app_name.lower().replace(".exe", "")
        if app_lower != "notepad":
            return

        for tab_path in _get_notepad_tabstate_dirs():
            cleared = 0
            for f in tab_path.iterdir():
                try:
                    f.unlink()
                    cleared += 1
                except Exception:
                    pass
            if cleared:
                logger.info(
                    f"Cleared {cleared} TabState files from {tab_path}"
                )

    def _find_window(
        self,
        app_name: str,
        title_fragment: Optional[str],
        temp_path: Optional[str],
    ) -> tuple[int, str]:
        """查找应用窗口."""
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32

            # 使用 wintypes 避免 py_object GC 问题
            WNDENUMPROC = ctypes.WINFUNCTYPE(
                wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
            )

            results: list[tuple[int, str]] = []

            def callback(hwnd, lparam):
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
                results.append((hwnd, title))
                return True

            enum_proc = WNDENUMPROC(callback)
            user32.EnumWindows(enum_proc, 0)

            # 匹配策略：临时文件名 > title_fragment > 通用匹配
            if temp_path:
                fname = Path(temp_path).name
                for hwnd, title in results:
                    if fname in title:
                        return (hwnd, title)

            if title_fragment:
                for hwnd, title in results:
                    if title_fragment.lower() in title.lower():
                        return (hwnd, title)

            # 通用匹配（中英文双语）
            app_lower = app_name.lower().replace(".exe", "")
            known_titles = {
                "notepad": ["记事本", "notepad", "untitled"],
                "calc": ["计算器", "calculator"],
                "calculator": ["计算器", "calculator"],
            }
            fragments = known_titles.get(app_lower, [app_lower])
            for hwnd, title in results:
                for frag in fragments:
                    if frag.lower() in title.lower():
                        return (hwnd, title)

        except Exception as e:
            logger.warning(f"Window search failed: {e}")

        return (0, "")

    def _focus_window(self, hwnd: int) -> None:
        """聚焦窗口."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            # SW_RESTORE = 9
            user32.ShowWindow(hwnd, 9)
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.3)
        except Exception as e:
            logger.warning(f"Focus window failed: {e}")
