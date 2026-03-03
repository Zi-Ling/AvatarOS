from pydantic import BaseModel, Field
from typing import List, Optional
import subprocess
import platform
import time
import logging
from ...base import BaseSkill, SkillSpec, SkillOutput, SkillMetadata, SkillDomain, SkillCapability
from ...registry import register_skill

logger = logging.getLogger(__name__)

# --- Inputs ---

class AppLaunchInput(BaseModel):
    name: str = Field(..., description="Name or path of the application to launch (e.g., 'notepad', 'calc', 'chrome')")
    args: Optional[List[str]] = Field(default=None, description="Optional command line arguments")

class WindowFocusInput(BaseModel):
    title: str = Field(..., description="Partial title of the window to focus (e.g., 'Untitled - Notepad')")

# --- Skills ---

@register_skill
class AppLaunchSkill(BaseSkill):
    spec = SkillSpec(
        name="computer.app.launch",
        api_name="computer.app.launch",
        internal_name="computer.app.launch_v1",
        aliases=["open_app", "launch_app", "start_app"],
        description="Launch an application by name or path. 启动应用程序。",
        input_model=AppLaunchInput,
        output_model=SkillOutput,
        category="computer",
        
        # Capability Routing
        meta=SkillMetadata(
            domain=SkillDomain.UI,
            capabilities={SkillCapability.EXECUTE, SkillCapability.CREATE}, # Create process
            risk_level="normal"
        ),
        
        synonyms=[
            "open application",
            "start program",
            "run app",
            "启动程序",
            "打开应用",
            "运行程序"
        ],
        tags=["computer", "app", "launch", "应用", "启动", "打开程序"]
    )

    def run(self, ctx: "SkillContext", input_data: AppLaunchInput) -> SkillOutput:
        app_name = input_data.name
        args = input_data.args or []
        
        try:
            if platform.system() == "Windows":
                # On Windows, os.startfile is good for opening files, but subprocess is better for apps
                # Using 'start' via shell=True allows launching by registered app name
                cmd = ["start", app_name] + args
                subprocess.Popen(" ".join(cmd), shell=True)
            elif platform.system() == "Darwin": # macOS
                cmd = ["open", "-a", app_name] + args
                subprocess.Popen(cmd)
            else: # Linux
                cmd = [app_name] + args
                subprocess.Popen(cmd)
                
            # Wait a bit for the app to potentially appear
            time.sleep(2) 
            return SkillOutput(success=True, message=f"Launched application: {app_name}")
        except Exception as e:
            logger.error(f"Failed to launch app {app_name}: {e}")
            return SkillOutput(success=False, message=f"Failed to launch {app_name}: {str(e)}")

@register_skill
class WindowFocusSkill(BaseSkill):
    spec = SkillSpec(
        name="computer.window.focus",
        api_name="computer.window.focus",
        internal_name="computer.window.focus_v1",
        aliases=["focus_window", "switch_window", "maximize_window"],
        description="Focus and maximize a window by its title. 聚焦并最大化窗口。",
        input_model=WindowFocusInput,
        output_model=SkillOutput,
        category="computer",
        
        # Capability Routing
        meta=SkillMetadata(
            domain=SkillDomain.UI,
            capabilities={SkillCapability.NAVIGATE, SkillCapability.MODIFY}, # Modify window state
            risk_level="low"
        ),
        
        synonyms=[
            "switch to window",
            "bring window to front",
            "maximize window",
            "切换窗口",
            "聚焦窗口",
            "最大化窗口"
        ],
        tags=["computer", "window", "focus", "窗口", "聚焦", "最大化"]
    )

    def run(self, ctx: "SkillContext", input_data: WindowFocusInput) -> SkillOutput:
        target_title = input_data.title.lower()
        
        try:
            import pygetwindow as gw
            
            # Find windows matching the title
            all_windows = gw.getAllTitles()
            matches = [w for w in all_windows if target_title in w.lower() and w.strip()]
            
            if not matches:
                return SkillOutput(success=False, message=f"No window found matching '{input_data.title}'")
            
            # Pick the first match
            window_title = matches[0]
            window = gw.getWindowsWithTitle(window_title)[0]
            
            if window.isMinimized:
                window.restore()
            
            try:
                window.activate()
            except Exception:
                # Sometimes activate fails on Windows if not allowed, try maximizing
                pass
                
            window.maximize()
            
            # Ensure it's really foreground
            time.sleep(0.5)
            
            return SkillOutput(success=True, message=f"Focused and maximized window: {window_title}")
            
        except ImportError:
            return SkillOutput(success=False, message="pygetwindow not installed. Cannot control windows.")
        except Exception as e:
            logger.error(f"Window control failed: {e}")
            return SkillOutput(success=False, message=f"Failed to focus window: {str(e)}")

