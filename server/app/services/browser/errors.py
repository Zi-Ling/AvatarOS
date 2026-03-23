# server/app/services/browser/errors.py
"""Browser Automation Executor 错误分类与规范化。"""
from __future__ import annotations

from typing import Any

from app.services.browser.models import (
    ActionResult,
    BrowserErrorCode,
    FailureContext,
    PageStateSnapshot,
)


class BrowserAutomationError(Exception):
    """Browser Automation Executor 异常基类。"""

    def __init__(self, message: str, error_code: BrowserErrorCode = BrowserErrorCode.UNKNOWN):
        super().__init__(message)
        self.error_code = error_code


class SessionCapacityError(BrowserAutomationError):
    """会话容量不足。"""

    def __init__(self, message: str = "Session capacity exhausted"):
        super().__init__(message, BrowserErrorCode.RESOURCE_EXHAUSTED)


class SessionNotFoundError(BrowserAutomationError):
    """会话不存在。"""

    def __init__(self, session_id: str):
        super().__init__(f"Session not found: {session_id}", BrowserErrorCode.CONTEXT_DESTROYED)


class ForbiddenActionError(BrowserAutomationError):
    """操作被安全策略禁止。"""

    def __init__(self, message: str = "Action forbidden by policy"):
        super().__init__(message, BrowserErrorCode.FORBIDDEN_ACTION)


# ── Playwright 异常映射 ───────────────────────────────────────────────

_PLAYWRIGHT_ERROR_MAP: dict[str, BrowserErrorCode] = {
    "TimeoutError": BrowserErrorCode.NAVIGATION_TIMEOUT,
    "timeout": BrowserErrorCode.NAVIGATION_TIMEOUT,
    "net::ERR_": BrowserErrorCode.NAVIGATION_FAILED,
    "Navigation failed": BrowserErrorCode.NAVIGATION_FAILED,
    "page crashed": BrowserErrorCode.PAGE_CRASHED,
    "Target closed": BrowserErrorCode.CONTEXT_DESTROYED,
    "context destroyed": BrowserErrorCode.CONTEXT_DESTROYED,
    "frame was detached": BrowserErrorCode.CONTEXT_DESTROYED,
    "Download failed": BrowserErrorCode.DOWNLOAD_FAILED,
    "File chooser": BrowserErrorCode.UPLOAD_FAILED,
    "Evaluation failed": BrowserErrorCode.JS_EVALUATION_ERROR,
    "Script timeout": BrowserErrorCode.SCRIPT_TIMEOUT,
    "ERR_BLOCKED_BY_RESPONSE": BrowserErrorCode.CROSS_ORIGIN_BLOCKED,
    "ERR_ACCESS_DENIED": BrowserErrorCode.CROSS_ORIGIN_BLOCKED,
    "net::ERR_ABORTED": BrowserErrorCode.NAVIGATION_FAILED,
    "401": BrowserErrorCode.AUTH_REQUIRED,
    "403": BrowserErrorCode.AUTH_REQUIRED,
}


def map_playwright_error(exc: Exception) -> BrowserErrorCode:
    """将 Playwright 异常映射为 BrowserErrorCode。"""
    exc_type = type(exc).__name__
    exc_msg = str(exc)

    # 先按异常类型匹配
    if exc_type in _PLAYWRIGHT_ERROR_MAP:
        return _PLAYWRIGHT_ERROR_MAP[exc_type]

    # 再按消息子串匹配
    for pattern, code in _PLAYWRIGHT_ERROR_MAP.items():
        if pattern in exc_msg:
            return code

    return BrowserErrorCode.UNKNOWN


def normalize_error(exc: Exception) -> BrowserErrorCode:
    """统一处理所有错误来源，返回标准化 BrowserErrorCode。"""
    # 已知的 BrowserAutomationError 子类
    if isinstance(exc, BrowserAutomationError):
        return exc.error_code

    # Playwright 异常
    exc_type = type(exc).__name__
    if exc_type in ("TimeoutError", "Error") or "playwright" in type(exc).__module__ if hasattr(type(exc), "__module__") else False:
        return map_playwright_error(exc)

    # 通用异常 — 尝试从消息推断
    exc_msg = str(exc).lower()
    if "selector" in exc_msg and "not found" in exc_msg:
        return BrowserErrorCode.SELECTOR_NOT_FOUND
    if "forbidden" in exc_msg or "policy" in exc_msg:
        return BrowserErrorCode.FORBIDDEN_ACTION
    if "timeout" in exc_msg:
        return BrowserErrorCode.ACTIONABILITY_TIMEOUT
    if "capacity" in exc_msg or "exhausted" in exc_msg or "quota" in exc_msg:
        return BrowserErrorCode.RESOURCE_EXHAUSTED
    if "verification" in exc_msg or "assert" in exc_msg:
        return BrowserErrorCode.UNKNOWN
    if "session" in exc_msg and ("not found" in exc_msg or "destroyed" in exc_msg):
        return BrowserErrorCode.CONTEXT_DESTROYED
    if "output" in exc_msg and "contract" in exc_msg:
        return BrowserErrorCode.UNKNOWN

    return map_playwright_error(exc)


def build_failure_context(
    *,
    url: str = "",
    title: str = "",
    error_code: BrowserErrorCode,
    error_message: str,
    completed_actions: list[ActionResult] | None = None,
    last_page_snapshot: PageStateSnapshot | None = None,
    error_stack_summary: str = "",
) -> FailureContext:
    """构建 FailureContext 辅助函数。"""
    return FailureContext(
        url=url,
        title=title,
        error_code=error_code,
        error_message=error_message,
        completed_actions=completed_actions or [],
        last_page_snapshot=last_page_snapshot,
        error_stack_summary=error_stack_summary,
    )
