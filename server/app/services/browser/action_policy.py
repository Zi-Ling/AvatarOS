# server/app/services/browser/action_policy.py
"""操作安全策略：三级分类 + 审批流程。"""
from __future__ import annotations

import asyncio
import re
from urllib.parse import urlparse

from app.services.browser.models import (
    ActionPolicyConfig,
    ActionPrimitive,
    ActionPrimitiveType,
    SecurityLevel,
)

# 默认 ALLOWED 操作
_DEFAULT_ALLOWED: set[ActionPrimitiveType] = {
    ActionPrimitiveType.CLICK,
    ActionPrimitiveType.FILL,
    ActionPrimitiveType.EXTRACT_TEXT,
    ActionPrimitiveType.EXTRACT_TABLE,
    ActionPrimitiveType.EXTRACT_LINKS,
    ActionPrimitiveType.WAIT_FOR,
    ActionPrimitiveType.SCREENSHOT,
    ActionPrimitiveType.HOVER,
    ActionPrimitiveType.SELECT_OPTION,
    ActionPrimitiveType.PRESS_KEY,
    ActionPrimitiveType.SCROLL,
    ActionPrimitiveType.GET_COOKIES,
    ActionPrimitiveType.CLOSE_TAB,
    ActionPrimitiveType.SWITCH_TAB,
}

# 默认 APPROVAL_REQUIRED 操作
_DEFAULT_APPROVAL: set[ActionPrimitiveType] = {
    ActionPrimitiveType.UPLOAD_FILE,
    ActionPrimitiveType.DOWNLOAD_WAIT,
    ActionPrimitiveType.SET_COOKIE,
    ActionPrimitiveType.DRAG_DROP,
    ActionPrimitiveType.HANDLE_DIALOG,
}


class ActionPolicy:
    """操作安全策略。"""

    def __init__(self, config: ActionPolicyConfig | None = None):
        self._config = config or ActionPolicyConfig()

    def classify(
        self,
        action: ActionPrimitive,
        current_url: str | None = None,
    ) -> SecurityLevel:
        """分类操作安全级别。"""
        at = action.action_type

        # 1. 检查 overrides
        override = self._config.overrides.get(at.value)
        if override is not None:
            return override

        # 2. navigate 特殊处理
        if at == ActionPrimitiveType.NAVIGATE:
            return self._classify_navigate(action, current_url)

        # 3. evaluate_js 特殊处理
        if at == ActionPrimitiveType.EVALUATE_JS:
            return self._classify_evaluate_js(action)

        # 4. 默认分类
        if at in _DEFAULT_ALLOWED:
            return SecurityLevel.ALLOWED
        if at in _DEFAULT_APPROVAL:
            return SecurityLevel.APPROVAL_REQUIRED

        return SecurityLevel.APPROVAL_REQUIRED

    def _classify_navigate(
        self, action: ActionPrimitive, current_url: str | None
    ) -> SecurityLevel:
        target_url = action.params.get("url", "")

        # file:// 协议禁止
        if target_url.startswith("file://"):
            return SecurityLevel.FORBIDDEN

        # 检查黑名单
        target_domain = self._extract_domain(target_url)
        if target_domain and target_domain in self._config.url_blacklist:
            return SecurityLevel.FORBIDDEN

        # 检查白名单
        if target_domain and target_domain in self._config.url_whitelist:
            return SecurityLevel.ALLOWED

        # 同域 vs 跨域
        if current_url:
            current_domain = self._extract_domain(current_url)
            if current_domain and target_domain and current_domain != target_domain:
                return SecurityLevel.APPROVAL_REQUIRED

        return SecurityLevel.ALLOWED

    def _classify_evaluate_js(self, action: ActionPrimitive) -> SecurityLevel:
        expression = action.params.get("expression", "")
        # 检查危险模式
        dangerous_patterns = [
            r"document\.cookie",
            r"fetch\s*\(",
            r"XMLHttpRequest",
            r"window\.open",
        ]
        for pattern in dangerous_patterns:
            if re.search(pattern, expression, re.IGNORECASE):
                return SecurityLevel.FORBIDDEN
        # 含副作用的 JS
        side_effect_patterns = [
            r"\.remove\s*\(",
            r"\.innerHTML\s*=",
            r"\.outerHTML\s*=",
            r"\.submit\s*\(",
            r"localStorage\.",
            r"sessionStorage\.",
        ]
        for pattern in side_effect_patterns:
            if re.search(pattern, expression, re.IGNORECASE):
                return SecurityLevel.APPROVAL_REQUIRED
        return SecurityLevel.ALLOWED

    @staticmethod
    def _extract_domain(url: str) -> str:
        try:
            parsed = urlparse(url)
            return parsed.hostname or ""
        except Exception:
            return ""

    async def request_approval(
        self, action: ActionPrimitive, reason: str
    ) -> bool:
        """请求审批，超时返回 False。"""
        # 当前实现：直接超时拒绝（后续可接入审批系统）
        timeout = self._config.approval_timeout_seconds
        try:
            await asyncio.wait_for(asyncio.sleep(timeout), timeout=0.01)
        except asyncio.TimeoutError:
            pass
        return False
