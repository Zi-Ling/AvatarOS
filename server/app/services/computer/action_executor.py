# app/services/computer/action_executor.py
"""ActionExecutor — 结构化 ActionPlan 执行器.

UIA-first 策略：对 CLICK 和 TYPE_TEXT 操作，优先尝试 UIA 语义操作
（InvokePattern / ValuePattern），失败后回退到键鼠驱动。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Optional

from .models import (
    ActionPlan,
    ActionResult,
    ActionType,
    ClickType,
    ComputerUseSessionState,
    DPIInfo,
    LocatorResult,
)

if TYPE_CHECKING:
    from .safety_guard import SafetyGuard
    from .uia_service import UIAutomationService

logger = logging.getLogger(__name__)


class ActionExecutor:
    """结构化 ActionPlan 执行器（UIA-first 策略）."""

    def __init__(
        self,
        mouse_driver: Any,
        keyboard_driver: Any,
        desktop_controller: Any,
        safety_guard: "SafetyGuard",
        uia_service: Optional["UIAutomationService"] = None,
        min_action_interval: float = 0.1,
    ) -> None:
        self._mouse = mouse_driver
        self._keyboard = keyboard_driver
        self._dc = desktop_controller
        self._guard = safety_guard
        self._uia = uia_service
        self._min_interval = min_action_interval
        self._last_action_time: float = 0.0
        self._dpi_info: Optional[DPIInfo] = None

    async def execute(
        self,
        action_plan: ActionPlan,
        locator_result: LocatorResult,
        session_state: ComputerUseSessionState,
        gui_state: Any = None,
    ) -> ActionResult:
        """执行单个 ActionPlan."""
        start = time.monotonic()

        # 1. Safety check
        if gui_state:
            safety = await self._guard.check_action(action_plan, session_state, gui_state)
            if not safety.allowed:
                return ActionResult(
                    success=False,
                    action_type=action_plan.action,
                    error=f"Safety blocked: {safety.reason}",
                )

        # 2. Rate limiting
        await self._enforce_rate_limit()

        # 3. Get target coords
        coords = locator_result.click_point
        if coords:
            coords = self._to_logical_coords(*coords)

        # 4. Execute action
        try:
            if action_plan.action == ActionType.CLICK:
                if not coords:
                    return ActionResult(success=False, action_type=action_plan.action, error="No click target")
                await self._execute_click(coords, action_plan.params.click_type, locator_result)
            elif action_plan.action == ActionType.TYPE_TEXT:
                text = action_plan.params.text or ""
                await self._execute_type_text(coords, text, locator_result)
            elif action_plan.action == ActionType.HOTKEY:
                keys = action_plan.params.keys or []
                await self._execute_hotkey(keys)
            elif action_plan.action == ActionType.SCROLL:
                direction = action_plan.params.direction
                amount = action_plan.params.amount
                await self._execute_scroll(coords, direction.value if direction else "down", amount)
            elif action_plan.action == ActionType.WAIT:
                await asyncio.sleep(action_plan.params.timeout)
            elif action_plan.action == ActionType.READ_SCREEN:
                pass  # No-op, observation only

            self._last_action_time = time.monotonic()
            duration = (time.monotonic() - start) * 1000

            return ActionResult(
                success=True,
                action_type=action_plan.action,
                target_coords=coords,
                locator_evidence=locator_result,
                duration_ms=duration,
            )
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            logger.error("Action execution failed: %s", e)
            return ActionResult(
                success=False,
                action_type=action_plan.action,
                target_coords=coords,
                error=str(e),
                duration_ms=duration,
            )

    # ── DPI handling ──────────────────────────────────────────────────

    def _get_dpi_info(self) -> DPIInfo:
        """获取当前显示器 DPI 缩放信息."""
        if self._dpi_info:
            return self._dpi_info
        try:
            import ctypes
            dpi = ctypes.windll.user32.GetDpiForSystem()
            scale = dpi / 96.0
            sw = ctypes.windll.user32.GetSystemMetrics(0)
            sh = ctypes.windll.user32.GetSystemMetrics(1)
            self._dpi_info = DPIInfo(
                scale_factor=scale,
                physical_size=(int(sw * scale), int(sh * scale)),
                logical_size=(sw, sh),
            )
        except Exception:
            self._dpi_info = DPIInfo()
        return self._dpi_info

    def _to_logical_coords(self, x: int, y: int) -> tuple[int, int]:
        """将物理像素坐标转换为 pyautogui 逻辑坐标."""
        dpi = self._get_dpi_info()
        if dpi.scale_factor == 1.0:
            return (x, y)
        return (int(x / dpi.scale_factor), int(y / dpi.scale_factor))

    # ── rate limiting ─────────────────────────────────────────────────

    async def _enforce_rate_limit(self) -> None:
        if self._last_action_time > 0:
            elapsed = time.monotonic() - self._last_action_time
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)

    # ── action implementations (UIA-first) ─────────────────────────────

    async def _execute_click(
        self, coords: tuple[int, int], click_type: ClickType = ClickType.SINGLE,
        locator_result: Optional[LocatorResult] = None,
    ) -> None:
        """UIA-first click: 先尝试 InvokePattern，失败回退坐标点击."""
        if (
            click_type == ClickType.SINGLE
            and self._uia
            and locator_result
            and locator_result.chosen_candidate
        ):
            info = locator_result.chosen_candidate.element_info or {}
            uia_kwargs: dict[str, Any] = {}
            if info.get("name"):
                uia_kwargs["name"] = info["name"]
            if info.get("automation_id"):
                uia_kwargs["automation_id"] = info["automation_id"]
            if info.get("control_type"):
                uia_kwargs["control_type"] = info["control_type"]

            if uia_kwargs:
                try:
                    ok = await self._uia.click_control(**uia_kwargs)
                    if ok:
                        logger.debug("UIA click_control succeeded: %s", uia_kwargs)
                        return
                    logger.debug("UIA click_control returned False, falling back to coords")
                except Exception as e:
                    logger.debug("UIA click_control failed (%s), falling back to coords", e)

        # 回退：坐标点击
        x, y = coords
        if click_type == ClickType.DOUBLE:
            await self._mouse.double_click(x, y)
        elif click_type == ClickType.RIGHT:
            await self._mouse.right_click(x, y)
        else:
            await self._mouse.click(x, y)

    async def _execute_type_text(
        self, coords: Optional[tuple[int, int]], text: str,
        locator_result: Optional[LocatorResult] = None,
    ) -> None:
        """UIA-first type: 先尝试 ValuePattern.SetValue，失败回退键盘输入."""
        if self._uia and locator_result and locator_result.chosen_candidate:
            info = locator_result.chosen_candidate.element_info or {}
            uia_kwargs: dict[str, Any] = {"value": text}
            if info.get("name"):
                uia_kwargs["name"] = info["name"]
            if info.get("automation_id"):
                uia_kwargs["automation_id"] = info["automation_id"]

            if len(uia_kwargs) > 1:  # 至少有 value + 一个定位属性
                try:
                    ok = await self._uia.set_control_value(**uia_kwargs)
                    if ok:
                        logger.debug("UIA set_control_value succeeded")
                        return
                    logger.debug("UIA set_control_value returned False, falling back to keyboard")
                except Exception as e:
                    logger.debug("UIA set_control_value failed (%s), falling back to keyboard", e)

        # 回退：键盘驱动
        if coords:
            await self._mouse.click(*coords)
            await asyncio.sleep(0.1)
        await self._keyboard.hotkey("ctrl", "a")
        await asyncio.sleep(0.05)
        await self._keyboard.press("delete")
        await asyncio.sleep(0.05)
        await self._keyboard.type_text(text)

    async def _execute_hotkey(self, keys: list[str]) -> None:
        if not keys:
            logger.warning("Hotkey called with empty keys, skipping")
            return
        result = self._keyboard.hotkey(*keys)
        if asyncio.iscoroutine(result):
            await result

    async def _execute_scroll(
        self,
        coords: Optional[tuple[int, int]],
        direction: str,
        amount: int,
    ) -> None:
        if coords:
            await self._mouse.move(*coords)
        clicks = amount if direction in ("up", "left") else -amount
        await self._mouse.scroll(clicks)
