# server/app/services/browser/action_dispatcher.py
"""操作调度器：接收 ActionPrimitive 列表并按序执行。"""
from __future__ import annotations

import logging
import time
from typing import Any

from app.services.browser.actionability import ActionabilityPipeline
from app.services.browser.action_policy import ActionPolicy
from app.services.browser.errors import (
    BrowserAutomationError,
    ForbiddenActionError,
    normalize_error,
    build_failure_context,
)
from app.services.browser.models import (
    ActionPrimitive,
    ActionPrimitiveType,
    ActionResult,
    BrowserErrorCode,
    BrowserVerificationResult,
    ExecutionResult,
    FailurePolicy,
    PageStateSnapshot,
    RecordingEntry,
    SecurityLevel,
    SelectorResolution,
)
from app.services.browser.page_snapshot import capture_snapshot, truncate_snapshot
from app.services.browser.selector_strategy import SelectorStrategy
from app.services.browser.verification_engine import VerificationEngine

logger = logging.getLogger(__name__)


# 需要可操作性检查的操作类型
_NEEDS_ACTIONABILITY = {
    ActionPrimitiveType.CLICK,
    ActionPrimitiveType.FILL,
    ActionPrimitiveType.HOVER,
    ActionPrimitiveType.SELECT_OPTION,
    ActionPrimitiveType.DRAG_DROP,
}


class ActionDispatcher:
    """操作调度器：接收 ActionPrimitive 列表并按序执行。"""

    def __init__(
        self,
        selector_strategy: SelectorStrategy | None = None,
        actionability_pipeline: ActionabilityPipeline | None = None,
        verification_engine: VerificationEngine | None = None,
    ):
        self._selector = selector_strategy or SelectorStrategy()
        self._actionability = actionability_pipeline or ActionabilityPipeline()
        self._verification = verification_engine or VerificationEngine()

    async def execute_action(
        self,
        action: ActionPrimitive,
        page: Any,
        policy: ActionPolicy,
    ) -> ActionResult:
        """执行单个操作原语。"""
        start = time.monotonic()
        current_url = page.url if hasattr(page, "url") else None

        # 1. 安全策略检查
        level = policy.classify(action, current_url)
        if level == SecurityLevel.FORBIDDEN:
            return ActionResult(
                success=False,
                error="Action forbidden by security policy",
                error_code=BrowserErrorCode.FORBIDDEN_ACTION,
                duration_ms=_elapsed(start),
            )
        if level == SecurityLevel.APPROVAL_REQUIRED:
            approved = await policy.request_approval(action, "Approval required")
            if not approved:
                return ActionResult(
                    success=False,
                    error="Action not approved",
                    error_code=BrowserErrorCode.FORBIDDEN_ACTION,
                    duration_ms=_elapsed(start),
                )

        # 2. 选择器解析
        selector_resolution: SelectorResolution | None = None
        resolved_selector = action.selector
        if action.selector_candidates:
            try:
                match_fn = self._make_match_fn(page)
                selector_resolution = self._selector.resolve(
                    action.selector_candidates, match_fn
                )
                resolved_selector = selector_resolution.adopted.expression
            except LookupError as exc:
                return ActionResult(
                    success=False,
                    error=str(exc),
                    error_code=BrowserErrorCode.SELECTOR_NOT_FOUND,
                    duration_ms=_elapsed(start),
                    selector_resolution=selector_resolution,
                )

        # 3. 可操作性检查
        if action.action_type in _NEEDS_ACTIONABILITY and resolved_selector:
            ar = await self._actionability.check(
                resolved_selector, page,
                timeout_ms=action.timeout_ms or 10000,
            )
            if not ar.actionable:
                return ActionResult(
                    success=False,
                    error=f"Actionability check failed: {ar.failure_reason}",
                    error_code=BrowserErrorCode.ACTIONABILITY_TIMEOUT,
                    duration_ms=_elapsed(start),
                    selector_resolution=selector_resolution,
                )

        # 4. 执行操作
        try:
            data = await self._dispatch(action, page, resolved_selector)
            result = ActionResult(
                success=True,
                data=data,
                duration_ms=_elapsed(start),
                selector_resolution=selector_resolution,
            )
        except Exception as exc:
            error_code = normalize_error(exc)
            result = ActionResult(
                success=False,
                error=str(exc),
                error_code=error_code,
                duration_ms=_elapsed(start),
                selector_resolution=selector_resolution,
            )

        # 5. action-level 验证
        if result.success and action.verification:
            vr = await self._verification.verify_action(action.verification, page)
            result.verification_result = vr
            if not vr.passed:
                result.success = False
                result.error = f"Verification failed: {vr.detail}"

        return result

    async def execute_sequence(
        self,
        actions: list[ActionPrimitive],
        page: Any,
        policy: ActionPolicy,
        failure_policy: FailurePolicy = FailurePolicy.FAIL_FAST,
        recording_enabled: bool = False,
    ) -> ExecutionResult:
        """按序执行操作序列。"""
        results: list[ActionResult] = []
        recordings: list[RecordingEntry] = []
        overall_start = time.monotonic()

        for action in actions:
            result = await self.execute_action(action, page, policy)
            results.append(result)

            if recording_enabled:
                recordings.append(RecordingEntry(
                    action=action,
                    selector_resolution=result.selector_resolution,
                    result=result,
                ))

            if not result.success and failure_policy == FailurePolicy.FAIL_FAST:
                return ExecutionResult(
                    success=False,
                    action_results=results,
                    error_code=result.error_code,
                    error_message=result.error,
                    total_duration_ms=_elapsed(overall_start),
                )

        has_failure = any(not r.success for r in results)
        return ExecutionResult(
            success=not has_failure,
            action_results=results,
            error_code=results[-1].error_code if has_failure and results else None,
            error_message=results[-1].error if has_failure and results else None,
            total_duration_ms=_elapsed(overall_start),
        )

    # ── 操作分发 ──────────────────────────────────────────────────────

    async def _dispatch(
        self, action: ActionPrimitive, page: Any, selector: str | None
    ) -> Any:
        """根据 action_type 分发到对应处理逻辑。"""
        handler = _ACTION_HANDLERS.get(action.action_type)
        if handler is None:
            raise BrowserAutomationError(
                f"Unsupported action type: {action.action_type}",
                BrowserErrorCode.UNKNOWN,
            )
        return await handler(page, action, selector)

    @staticmethod
    def _make_match_fn(page: Any):
        """创建选择器匹配函数（同步包装）。"""
        import asyncio

        def match_fn(expression: str) -> int:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 在异步上下文中无法同步等待，默认返回 1
                    return 1
                coro = page.query_selector_all(expression)
                elements = loop.run_until_complete(coro)
                return len(elements) if elements else 0
            except Exception:
                return 1  # 无法检测时假设匹配
        return match_fn


# ── 操作处理函数 ──────────────────────────────────────────────────────

async def _handle_navigate(page, action, selector) -> Any:
    url = action.params.get("url", "")
    wait_until = action.params.get("wait_until", "load")
    await page.goto(url, wait_until=wait_until)
    return {"url": page.url if hasattr(page, "url") else url}


async def _handle_click(page, action, selector) -> Any:
    await page.click(selector)
    return None


async def _handle_fill(page, action, selector) -> Any:
    value = action.params.get("value", "")
    await page.fill(selector, value)
    return None


async def _handle_extract_text(page, action, selector) -> Any:
    text = await page.text_content(selector)
    return text or ""


async def _handle_extract_table(page, action, selector) -> Any:
    rows = await page.evaluate(
        """(sel) => {
            const table = document.querySelector(sel);
            if (!table) return [];
            return Array.from(table.rows).map(row =>
                Array.from(row.cells).map(cell => cell.textContent.trim())
            );
        }""",
        selector,
    )
    return rows or []


async def _handle_extract_links(page, action, selector) -> Any:
    links = await page.evaluate(
        """(sel) => {
            const container = sel ? document.querySelector(sel) : document;
            if (!container) return [];
            return Array.from(container.querySelectorAll('a')).map(a => ({
                text: a.textContent.trim(),
                href: a.href,
            }));
        }""",
        selector,
    )
    return links or []


async def _handle_wait_for(page, action, selector) -> Any:
    state = action.params.get("state", "visible")
    timeout = action.timeout_ms or 10000
    await page.wait_for_selector(selector, state=state, timeout=timeout)
    return None


async def _handle_screenshot(page, action, selector) -> Any:
    path = action.params.get("path", "screenshot.png")
    if selector:
        el = await page.query_selector(selector)
        if el:
            await el.screenshot(path=path)
        else:
            await page.screenshot(path=path)
    else:
        await page.screenshot(path=path)
    return {"path": path}


async def _handle_hover(page, action, selector) -> Any:
    await page.hover(selector)
    return None


async def _handle_select_option(page, action, selector) -> Any:
    value = action.params.get("value", "")
    await page.select_option(selector, value)
    return None


async def _handle_press_key(page, action, selector) -> Any:
    key = action.params.get("key", "")
    if selector:
        await page.press(selector, key)
    else:
        await page.keyboard.press(key)
    return None


async def _handle_scroll(page, action, selector) -> Any:
    x = action.params.get("x", 0)
    y = action.params.get("y", 0)
    await page.evaluate(f"window.scrollBy({x}, {y})")
    return None


async def _handle_evaluate_js(page, action, selector) -> Any:
    expression = action.params.get("expression", "")
    result = await page.evaluate(expression)
    return result


async def _handle_upload_file(page, action, selector) -> Any:
    file_path = action.params.get("file_path", "")
    el = await page.query_selector(selector)
    if el:
        await el.set_input_files(file_path)
    return {"file_path": file_path}


async def _handle_download_wait(page, action, selector) -> Any:
    async with page.expect_download() as download_info:
        if selector:
            await page.click(selector)
    download = await download_info.value
    path = await download.path()
    return {"download_path": str(path) if path else ""}


async def _handle_drag_drop(page, action, selector) -> Any:
    target = action.params.get("target_selector", "")
    await page.drag_and_drop(selector, target)
    return None


async def _handle_switch_tab(page, action, selector) -> Any:
    # page_id or index based switching handled at executor level
    index = action.params.get("index", 0)
    return {"switched_to": index}


async def _handle_close_tab(page, action, selector) -> Any:
    await page.close()
    return None


async def _handle_dialog(page, action, selector) -> Any:
    dialog_action = action.params.get("action", "dismiss")
    prompt_text = action.params.get("prompt_text", "")
    # Dialog handling is typically set up via page.on("dialog")
    return {"action": dialog_action, "prompt_text": prompt_text}


async def _handle_set_cookie(page, action, selector) -> Any:
    cookies = action.params.get("cookies", [])
    context = page.context if hasattr(page, "context") else None
    if context:
        await context.add_cookies(cookies)
    return None


async def _handle_get_cookies(page, action, selector) -> Any:
    context = page.context if hasattr(page, "context") else None
    if context:
        cookies = await context.cookies()
        return cookies
    return []


# ── 操作处理函数映射 ──────────────────────────────────────────────────

_ACTION_HANDLERS: dict[ActionPrimitiveType, Any] = {
    ActionPrimitiveType.NAVIGATE: _handle_navigate,
    ActionPrimitiveType.CLICK: _handle_click,
    ActionPrimitiveType.FILL: _handle_fill,
    ActionPrimitiveType.EXTRACT_TEXT: _handle_extract_text,
    ActionPrimitiveType.EXTRACT_TABLE: _handle_extract_table,
    ActionPrimitiveType.EXTRACT_LINKS: _handle_extract_links,
    ActionPrimitiveType.WAIT_FOR: _handle_wait_for,
    ActionPrimitiveType.SCREENSHOT: _handle_screenshot,
    ActionPrimitiveType.HOVER: _handle_hover,
    ActionPrimitiveType.SELECT_OPTION: _handle_select_option,
    ActionPrimitiveType.PRESS_KEY: _handle_press_key,
    ActionPrimitiveType.SCROLL: _handle_scroll,
    ActionPrimitiveType.EVALUATE_JS: _handle_evaluate_js,
    ActionPrimitiveType.UPLOAD_FILE: _handle_upload_file,
    ActionPrimitiveType.DOWNLOAD_WAIT: _handle_download_wait,
    ActionPrimitiveType.DRAG_DROP: _handle_drag_drop,
    ActionPrimitiveType.SWITCH_TAB: _handle_switch_tab,
    ActionPrimitiveType.CLOSE_TAB: _handle_close_tab,
    ActionPrimitiveType.HANDLE_DIALOG: _handle_dialog,
    ActionPrimitiveType.SET_COOKIE: _handle_set_cookie,
    ActionPrimitiveType.GET_COOKIES: _handle_get_cookies,
}


def _elapsed(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 2)
