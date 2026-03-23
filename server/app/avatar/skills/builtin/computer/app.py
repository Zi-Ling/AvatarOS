# app/avatar/skills/builtin/computer/app.py

from pydantic import BaseModel, Field
from typing import List, Optional
import subprocess
import platform
import time
import logging
from ...base import BaseSkill, SkillSpec, SkillOutput, SideEffect, SkillRiskLevel
from ...registry import register_skill

logger = logging.getLogger(__name__)


class AppLaunchInput(BaseModel):
    name: str = Field(..., description="Name or path of the application to launch (e.g., 'notepad', 'calc', 'chrome')")
    args: Optional[List[str]] = Field(default=None, description="Optional command line arguments")


class WindowFocusInput(BaseModel):
    title: str = Field(..., description="Partial title of the window to focus (e.g., 'Untitled - Notepad')")


@register_skill
class AppLaunchSkill(BaseSkill):
    spec = SkillSpec(
        name="computer.app.launch",
        description="Launch an application by name or path. 启动应用程序。",
        input_model=AppLaunchInput,
        output_model=SkillOutput,
        side_effects={SideEffect.EXEC},
        risk_level=SkillRiskLevel.EXECUTE,
        aliases=["open_app", "launch_app", "start_app"],
        tags=["launch", "open", "start", "app", "启动", "打开", "应用"],
        requires_host_desktop=True,
    )

    async def run(self, ctx, input_data: AppLaunchInput) -> SkillOutput:
        app_name = input_data.name
        args = input_data.args or []
        try:
            if platform.system() == "Windows":
                cmd = ["start", app_name] + args
                subprocess.Popen(" ".join(cmd), shell=True)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", "-a", app_name] + args)
            else:
                subprocess.Popen([app_name] + args)
            time.sleep(2)
            return SkillOutput(success=True, message=f"Launched application: {app_name}")
        except Exception as e:
            logger.error(f"Failed to launch app {app_name}: {e}")
            return SkillOutput(success=False, message=f"Failed to launch {app_name}: {str(e)}")


@register_skill
class WindowFocusSkill(BaseSkill):
    spec = SkillSpec(
        name="computer.window.focus",
        description="Focus and maximize a window by its title. 聚焦并最大化窗口。",
        input_model=WindowFocusInput,
        output_model=SkillOutput,
        side_effects=set(),
        risk_level=SkillRiskLevel.WRITE,
        aliases=["focus_window", "switch_window", "maximize_window"],
        tags=["window", "focus", "switch", "maximize", "窗口", "聚焦", "切换", "最大化"],
        requires_host_desktop=True,
    )

    async def run(self, ctx, input_data: WindowFocusInput) -> SkillOutput:
        target_title = input_data.title.lower()
        try:
            import pygetwindow as gw
            all_windows = gw.getAllTitles()
            matches = [w for w in all_windows if target_title in w.lower() and w.strip()]
            if not matches:
                return SkillOutput(success=False, message=f"No window found matching '{input_data.title}'")
            window_title = matches[0]
            window = gw.getWindowsWithTitle(window_title)[0]
            if window.isMinimized:
                window.restore()
            try:
                window.activate()
            except Exception:
                pass
            window.maximize()
            time.sleep(0.5)
            return SkillOutput(success=True, message=f"Focused and maximized window: {window_title}")
        except ImportError:
            return SkillOutput(success=False, message="pygetwindow not installed.")
        except Exception as e:
            logger.error(f"Window control failed: {e}")
            return SkillOutput(success=False, message=f"Failed to focus window: {str(e)}")
