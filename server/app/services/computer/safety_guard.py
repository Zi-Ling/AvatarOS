# app/services/computer/safety_guard.py
"""SafetyGuard — 操作分级 + 审批 + 黑名单 + 危险关键词."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from .models import (
    ActionPlan,
    ActionType,
    ComputerUseSessionState,
    GUIState,
    OperationLevel,
    SafetyCheckResult,
)

logger = logging.getLogger(__name__)

_DEFAULT_BLACKLIST = [
    "taskmgr", "regedit", "系统托盘",
    "Task Manager", "Registry Editor",
]

_DEFAULT_DANGEROUS_KEYWORDS = [
    "删除", "格式化", "关机", "重启", "卸载", "清空",
    "delete", "format", "shutdown", "restart", "uninstall", "erase",
    "rm -rf", "del /f", "fdisk",
]


class SafetyGuard:
    """操作安全守卫."""

    def __init__(
        self,
        approval_service: Any = None,
        blacklist: Optional[list[str]] = None,
        dangerous_keywords: Optional[list[str]] = None,
        max_steps: int = 50,
        max_duration_seconds: int = 600,
    ) -> None:
        self._approval = approval_service
        self._blacklist = blacklist or list(_DEFAULT_BLACKLIST)
        self._dangerous_keywords = dangerous_keywords or list(_DEFAULT_DANGEROUS_KEYWORDS)
        self._max_steps = max_steps
        self._max_duration = max_duration_seconds

    async def check_action(
        self,
        action_plan: ActionPlan,
        session_state: ComputerUseSessionState,
        gui_state: GUIState,
    ) -> SafetyCheckResult:
        """安全检查."""
        # 1. Blacklist check
        window = gui_state.window_title.lower()
        for bl in self._blacklist:
            if bl.lower() in window:
                return SafetyCheckResult(
                    allowed=False,
                    reason=f"Target window '{gui_state.window_title}' is blacklisted",
                    operation_level=OperationLevel.DANGEROUS,
                )

        # 2. Step limit
        if session_state.current_step_index >= self._max_steps:
            return SafetyCheckResult(
                allowed=False,
                reason=f"Step limit {self._max_steps} exceeded",
            )

        # 3. Duration limit
        elapsed = time.time() - session_state.started_at
        if elapsed > self._max_duration:
            return SafetyCheckResult(
                allowed=False,
                reason=f"Duration limit {self._max_duration}s exceeded",
            )

        # 4. Classify action
        ocr_text = gui_state.extracted_text
        level = self.classify_action(action_plan, gui_state, ocr_text)

        # 5. DANGEROUS → require approval
        if level == OperationLevel.DANGEROUS:
            if self._approval:
                try:
                    req_id = await self._approval.request_approval(
                        action_description=action_plan.target.description,
                        operation_level=level.value,
                    )
                    return SafetyCheckResult(
                        allowed=False,
                        reason="Dangerous action requires approval",
                        requires_approval=True,
                        approval_request_id=req_id,
                        operation_level=level,
                    )
                except Exception as e:
                    return SafetyCheckResult(
                        allowed=False,
                        reason=f"Approval request failed: {e}",
                        requires_approval=True,
                        operation_level=level,
                    )
            return SafetyCheckResult(
                allowed=False,
                reason="Dangerous action requires approval (no approval service)",
                requires_approval=True,
                operation_level=level,
            )

        return SafetyCheckResult(allowed=True, operation_level=level)

    def classify_action(
        self,
        action_plan: ActionPlan,
        gui_state: GUIState,
        ocr_text: str = "",
    ) -> OperationLevel:
        """动作分级（增强版）."""
        action = action_plan.action
        target_desc = action_plan.target.description

        # Base classification by action type
        if action == ActionType.READ_SCREEN:
            base_level = OperationLevel.READ
        elif action == ActionType.WAIT:
            base_level = OperationLevel.READ
        elif action in (ActionType.CLICK, ActionType.TYPE_TEXT, ActionType.SCROLL):
            base_level = OperationLevel.WRITE
        elif action == ActionType.HOTKEY:
            # Check for dangerous hotkeys
            keys = action_plan.params.keys or []
            keys_lower = [k.lower() for k in keys]
            if "alt" in keys_lower and "f4" in keys_lower:
                base_level = OperationLevel.DANGEROUS
            else:
                base_level = OperationLevel.WRITE
        else:
            base_level = OperationLevel.WRITE

        # Elevate if dangerous keywords found
        if self._check_dangerous_keywords(target_desc, ocr_text):
            return OperationLevel.DANGEROUS

        # Elevate if system settings window
        sys_windows = ["设置", "settings", "control panel", "控制面板", "系统"]
        window_lower = gui_state.window_title.lower()
        if any(sw in window_lower for sw in sys_windows):
            if base_level == OperationLevel.WRITE:
                return OperationLevel.DANGEROUS

        return base_level

    def _check_dangerous_keywords(
        self,
        target_description: str,
        ocr_text: str = "",
    ) -> bool:
        """检查目标描述和 OCR 文本中是否包含危险关键词."""
        combined = f"{target_description} {ocr_text}".lower()
        return any(kw.lower() in combined for kw in self._dangerous_keywords)
