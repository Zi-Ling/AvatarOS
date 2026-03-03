# avatar/actions/shell/local.py
from __future__ import annotations

import subprocess
from typing import Optional

from ..base import ActionResult, ShellActionContext


def run_command(cmd: str, *, ctx: Optional[ShellActionContext] = None, timeout: int = 20) -> ActionResult:
    """
    Execute a shell command locally.
    """
    try:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=ctx.cwd if ctx else None,
            text=True,
        )
        out, err = proc.communicate(timeout=timeout)

        return ActionResult(
            success=proc.returncode == 0,
            output=out,
            error=err if proc.returncode != 0 else None,
        )
    except Exception as e:  # noqa: BLE001
        return ActionResult(success=False, error=str(e))
