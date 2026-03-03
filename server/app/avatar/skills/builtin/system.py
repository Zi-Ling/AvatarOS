# app/avatar/skills/builtin/system.py

from __future__ import annotations

import os
import sys
import asyncio
import subprocess
from pathlib import Path
from typing import Optional, Any
from pydantic import Field, model_validator
from ..common.path_mixins import PathBindMixin

from ..base import BaseSkill, SkillSpec, SkillCategory, SkillPermission, SkillMetadata, SkillDomain, SkillCapability
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext


# ============================================================================
# system.echo
# ============================================================================

class EchoInput(SkillInput):
    message: str = Field(..., description="Message to echo back.")

class EchoOutput(SkillOutput):
    echo: str

@register_skill
class SystemEchoSkill(BaseSkill[EchoInput, EchoOutput]):
    spec = SkillSpec(
        name="system.echo",
        api_name="system.echo",
        aliases=["echo", "print"],
        description="Echo back the given message. 回显给定消息。",
        category=SkillCategory.SYSTEM,
        input_model=EchoInput,
        output_model=EchoOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.SYSTEM,
            capabilities=set(),
            risk_level="low"
        ),
        
        synonyms=[
            "print message",
            "echo text",
            "输出消息",
            "打印文本"
        ],
        examples=[
            {"description": "Echo message", "params": {"message": "Hello World"}}
        ],
        tags=["system", "test", "echo"]
    )

    async def run(self, ctx: SkillContext, params: EchoInput) -> EchoOutput:
        return EchoOutput(
            success=True,
            message=params.message,
            echo=params.message
        )


# ============================================================================
# system.run_command
# ============================================================================

class RunCommandInput(SkillInput):
    command: str = Field(..., description="Command to run in shell.")
    timeout: int = Field(60, description="Timeout in seconds.")

class RunCommandOutput(SkillOutput):
    command: str
    returncode: int
    stdout: str
    stderr: str

@register_skill
class SystemRunCommandSkill(BaseSkill[RunCommandInput, RunCommandOutput]):
    spec = SkillSpec(
        name="system.run_command",
        api_name="system.run_command",
        aliases=["shell.exec", "cmd.run", "system.exec"],
        description="Run a system command and capture its output. DO NOT use this for Python scripts, plotting, or data processing (use python.run instead). Use this for shell commands like 'git', 'npm', 'ls', 'mkdir', etc. 运行系统命令并获取输出。",
        category=SkillCategory.SYSTEM,
        input_model=RunCommandInput,
        output_model=RunCommandOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.SYSTEM,
            capabilities={SkillCapability.EXECUTE},
            risk_level="critical"
        ),
        
        permissions=[
            SkillPermission(name="system_exec", description="Execute arbitrary system commands")
        ],
        synonyms=[
            "run shell command",
            "execute command",
            "运行命令",
            "执行命令",
            "shell命令"
        ],
        examples=[
            {"description": "Run git command", "params": {"command": "git status"}}
        ],
        tags=["system", "shell", "dangerous", "系统", "命令", "执行"]
    )

    async def run(self, ctx: SkillContext, params: RunCommandInput) -> RunCommandOutput:
        if ctx.dry_run:
            return RunCommandOutput(
                success=True,
                message=f"[dry_run] Would run: {params.command}",
                command=params.command,
                returncode=0,
                stdout="",
                stderr=""
            )

        try:
            # Pre-execution: Validate command is not empty
            if not params.command.strip():
                return RunCommandOutput(
                    success=False,
                    message="Command is empty",
                    command=params.command,
                    returncode=-1,
                    stdout="",
                    stderr="Empty command"
                )
            
            # Execute in the correct working directory
            result = await asyncio.to_thread(
                subprocess.run,
                params.command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=params.timeout,
                cwd=str(ctx.base_path) if ctx.base_path else None,
            )
            
            # Post-execution verification
            # Verify returncode is a valid integer
            if not isinstance(result.returncode, int):
                return RunCommandOutput(
                    success=False,
                    message=f"Verification Failed: Invalid return code type: {type(result.returncode)}",
                    command=params.command,
                    returncode=-1,
                    stdout=result.stdout or "",
                    stderr=result.stderr or ""
                )
            
            # Success is determined by exit code 0
            success = result.returncode == 0
            
            # Provide detailed message
            if success:
                msg = f"Command succeeded (exit code: 0)"
                if result.stdout:
                    msg += f", output: {len(result.stdout)} chars"
            else:
                msg = f"Command failed (exit code: {result.returncode})"
                if result.stderr:
                    msg += f", error: {result.stderr[:100]}"
            
            return RunCommandOutput(
                success=success,
                message=msg,
                command=params.command,
                returncode=result.returncode,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
            )
        except subprocess.TimeoutExpired as e:
             return RunCommandOutput(
                success=False,
                message=f"Timeout: Command exceeded {params.timeout}s limit",
                command=params.command,
                returncode=-1,
                stdout=str(e.stdout) if e.stdout else "",
                stderr=f"TimeoutError: {str(e)}",
            )
        except FileNotFoundError as e:
            return RunCommandOutput(
                success=False,
                message=f"Command not found: {e}",
                command=params.command,
                returncode=-1,
                stdout="",
                stderr=str(e)
            )
        except Exception as e:
            return RunCommandOutput(
                success=False,
                message=f"Execution failed: {str(e)}",
                command=params.command,
                returncode=-1,
                stdout="",
                stderr=str(e)
            )

# ============================================================================
# system.open_path
# ============================================================================

class OpenPathInput(PathBindMixin, SkillInput):
    # relative_path 可以允许为空，因为有可能完全靠 file_path/abs_path 驱动
    relative_path: str | None = Field(
        None,
        description="Relative path to open (relative to base_path). Can also be an absolute path."
    )
    
    # 可选：增加一个 abs_path，直接使用绝对路径时用
    abs_path: str | None = Field(
        None, description="Absolute file path. If provided, takes precedence."
    )

class OpenPathOutput(SkillOutput):
    path: str


@register_skill
class SystemOpenPathSkill(BaseSkill[OpenPathInput, OpenPathOutput]):
    spec = SkillSpec(
        name="system.open_path",
        api_name="system.open_path",
        aliases=["file.open", "open", "start"],
        description="Open a file or directory with the OS default application. 使用系统默认应用打开文件或目录。",
        category=SkillCategory.SYSTEM,
        input_model=OpenPathInput,
        output_model=OpenPathOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.SYSTEM,
            capabilities={SkillCapability.EXECUTE},
            risk_level="normal"
        ),
        
        permissions=[
            SkillPermission(name="system_open", description="Open files in external applications")
        ],
        synonyms=[
            "open file",
            "open folder",
            "launch application",
            "打开文件",
            "打开文件夹",
            "启动应用"
        ],
        examples=[
            {"description": "Open file", "params": {"relative_path": "document.pdf"}}
        ],
        tags=["system", "ui", "文件", "打开"]
    )

    async def run(self, ctx: SkillContext, params: OpenPathInput) -> OpenPathOutput:
        # 1) 基础校验：路径不能为空
        # 优先使用 abs_path
        if params.abs_path:
             target_path = Path(params.abs_path)
        # 否则使用 relative_path
        elif params.relative_path:
             target_path = ctx.resolve_path(params.relative_path)
        # 如果都没有，报错
        else:
             return OpenPathOutput(
                success=False,
                message="No valid path provided (neither relative_path nor abs_path).",
                path=""
            )

        # dry_run：只报告将要做什么
        if ctx.dry_run:
            return OpenPathOutput(
                success=True,
                message=f"[dry_run] Would open: {target_path}",
                path=str(target_path),
            )

        # 3) 实际打开
        try:
            if not target_path.exists():
                return OpenPathOutput(
                    success=False,
                    message=f"Path not found: {target_path}",
                    path=str(target_path),
                )

            # 允许既是文件也可以是目录：目录用资源管理器打开
            if sys.platform.startswith("win"):
                os.startfile(str(target_path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target_path)])
            else:
                subprocess.Popen(["xdg-open", str(target_path)])

            return OpenPathOutput(
                success=True,
                message=f"Opened: {target_path}",
                path=str(target_path),
            )

        except Exception as e:
            return OpenPathOutput(
                success=False,
                message=f"Failed to open '{target_path}': {e}",
                path=str(target_path),
            )

