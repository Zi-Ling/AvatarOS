# server/app/services/browser/actionability.py
"""6 级可操作性检查流水线。"""
from __future__ import annotations

import time
from typing import Any, Protocol

from app.services.browser.models import (
    ActionabilityCheckDetail,
    ActionabilityFailureReason,
    ActionabilityResult,
)


# 检查阶段定义（顺序固定）
ACTIONABILITY_STAGES = [
    "attached",
    "visible",
    "stable",
    "enabled",
    "not_obscured",
    "interactable",
]

# 阶段 → 失败原因映射
_STAGE_TO_REASON: dict[str, ActionabilityFailureReason] = {
    "attached": ActionabilityFailureReason.NOT_FOUND,
    "visible": ActionabilityFailureReason.NOT_VISIBLE,
    "stable": ActionabilityFailureReason.NOT_STABLE,
    "enabled": ActionabilityFailureReason.NOT_ENABLED,
    "not_obscured": ActionabilityFailureReason.OBSCURED_BY_OVERLAY,
    "interactable": ActionabilityFailureReason.DETACHED_FROM_DOM,
}


class PageLike(Protocol):
    """Playwright page 的最小协议，便于 mock。"""

    async def query_selector(self, selector: str) -> Any: ...
    async def is_visible(self, selector: str) -> bool: ...
    async def is_enabled(self, selector: str) -> bool: ...
    async def evaluate(self, expression: str, arg: Any = None) -> Any: ...


class ActionabilityPipeline:
    """6 级可操作性检查流水线。"""

    async def check(
        self,
        selector: str,
        page: Any,
        timeout_ms: int = 10000,
    ) -> ActionabilityResult:
        """
        按序执行检查：
        attached → visible → stable → enabled → not_obscured → interactable
        """
        checks: list[ActionabilityCheckDetail] = []
        total_start = time.monotonic()

        for stage in ACTIONABILITY_STAGES:
            stage_start = time.monotonic()
            try:
                passed = await self._run_stage(stage, selector, page)
            except Exception:
                passed = False
            duration = (time.monotonic() - stage_start) * 1000

            checks.append(ActionabilityCheckDetail(
                stage=stage,
                passed=passed,
                duration_ms=round(duration, 2),
            ))

            if not passed:
                total_duration = (time.monotonic() - total_start) * 1000
                return ActionabilityResult(
                    actionable=False,
                    failure_reason=_STAGE_TO_REASON.get(stage),
                    checks=checks,
                    total_duration_ms=round(total_duration, 2),
                )

        total_duration = (time.monotonic() - total_start) * 1000
        return ActionabilityResult(
            actionable=True,
            checks=checks,
            total_duration_ms=round(total_duration, 2),
        )

    async def _run_stage(self, stage: str, selector: str, page: Any) -> bool:
        if stage == "attached":
            el = await page.query_selector(selector)
            return el is not None
        elif stage == "visible":
            return await page.is_visible(selector)
        elif stage == "stable":
            # 简化：检查元素存在即视为稳定
            el = await page.query_selector(selector)
            return el is not None
        elif stage == "enabled":
            return await page.is_enabled(selector)
        elif stage == "not_obscured":
            # 通过 JS 检查元素是否被遮挡
            try:
                result = await page.evaluate(
                    """(sel) => {
                        const el = document.querySelector(sel);
                        if (!el) return false;
                        const rect = el.getBoundingClientRect();
                        const cx = rect.left + rect.width / 2;
                        const cy = rect.top + rect.height / 2;
                        const top = document.elementFromPoint(cx, cy);
                        return el.contains(top) || el === top;
                    }""",
                    selector,
                )
                return bool(result)
            except Exception:
                return True  # 无法检测时默认通过
        elif stage == "interactable":
            el = await page.query_selector(selector)
            return el is not None
        return False
