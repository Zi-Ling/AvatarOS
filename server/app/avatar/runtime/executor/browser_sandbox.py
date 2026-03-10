# app/avatar/runtime/executor/browser_sandbox.py
"""
BrowserSandboxExecutor — 浏览器专用执行器

browser.run skill 的执行模型与 python.run 完全不同：
- python.run：把代码字符串扔进容器执行
- browser.run：skill 本身管理 Playwright 进程，直接在本地异步运行

因此 BrowserSandboxExecutor 不走容器 exec，而是直接调用 skill.run()，
与 LocalExecutor 语义相同，但只接受 BROWSER side_effect 的 skill。

网络隔离说明：
- 当前阶段 Playwright 在宿主机进程内运行，有完整网络访问
- 未来如需更强隔离，可在此层接入 egress proxy 或 network namespace
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .base import SkillExecutor
from app.avatar.skills.base import SideEffect

logger = logging.getLogger(__name__)


class BrowserSandboxExecutor(SkillExecutor):
    """
    浏览器专用执行器。

    直接在本地进程执行 browser.run skill（Playwright 自管理），
    不通过容器 exec，因为 browser.run 的执行逻辑在 skill 内部。
    """

    def health_check(self) -> bool:
        return True

    def supports(self, skill: Any) -> bool:
        try:
            return SideEffect.BROWSER in skill.spec.side_effects
        except Exception:
            return False

    async def execute(self, skill: Any, input_data: Any, context: Any) -> Any:
        logger.debug(f"[BrowserSandboxExecutor] Executing {skill.spec.name} in-process")
        try:
            result = skill.run(context, input_data)
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except Exception as e:
            logger.error(f"[BrowserSandboxExecutor] Failed: {skill.spec.name}, error: {e}")
            raise

    def cleanup(self):
        pass
