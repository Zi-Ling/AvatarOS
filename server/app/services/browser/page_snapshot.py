# server/app/services/browser/page_snapshot.py
"""PageStateSnapshot 采集与截断。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.browser.models import (
    DialogInfo,
    FormFieldSummary,
    InteractiveElementSummary,
    PageStateSnapshot,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def capture_snapshot(page: Any) -> PageStateSnapshot:
    """从 Playwright page 采集结构化快照。"""
    url = page.url if hasattr(page, "url") else ""
    title = await page.title() if hasattr(page, "title") and callable(page.title) else ""

    # 采集可交互元素
    elements: list[InteractiveElementSummary] = []
    try:
        raw = await page.evaluate("""() => {
            const els = document.querySelectorAll(
                'a, button, input, select, textarea, [role="button"], [onclick]'
            );
            return Array.from(els).slice(0, 60).map(el => ({
                selector: el.tagName.toLowerCase() +
                    (el.id ? '#' + el.id : '') +
                    (el.className ? '.' + el.className.split(' ')[0] : ''),
                tag: el.tagName.toLowerCase(),
                text: (el.textContent || '').trim().slice(0, 100),
                role: el.getAttribute('role') || '',
                enabled: !el.disabled,
            }));
        }""")
        for item in (raw or []):
            elements.append(InteractiveElementSummary(**item))
    except Exception:
        pass

    # 采集表单字段
    form_fields: list[FormFieldSummary] = []
    try:
        raw_fields = await page.evaluate("""() => {
            const fields = document.querySelectorAll('input, select, textarea');
            return Array.from(fields).slice(0, 50).map(el => ({
                name: el.name || el.id || '',
                field_type: el.type || el.tagName.toLowerCase(),
                value: el.value || '',
                required: el.required || false,
            }));
        }""")
        for item in (raw_fields or []):
            form_fields.append(FormFieldSummary(**item))
    except Exception:
        pass

    snapshot = PageStateSnapshot(
        url=url,
        title=title,
        timestamp=_now(),
        interactive_elements_summary=elements,
        form_fields=form_fields,
    )
    return truncate_snapshot(snapshot)


def truncate_snapshot(snapshot: PageStateSnapshot) -> PageStateSnapshot:
    """
    截断快照以满足大小限制。
    截断优先级：active_dialogs > form_fields > interactive_elements
    （对话框最重要，可交互元素最先被截断）
    """
    # 1. 先截断 interactive_elements 到 MAX
    max_el = PageStateSnapshot.MAX_INTERACTIVE_ELEMENTS
    if len(snapshot.interactive_elements_summary) > max_el:
        snapshot.interactive_elements_summary = snapshot.interactive_elements_summary[:max_el]
        snapshot.truncated = True

    # 2. 检查序列化大小，超过 64KB 时进一步截断
    max_bytes = PageStateSnapshot.MAX_SERIALIZED_BYTES
    serialized = snapshot.model_dump_json()

    if len(serialized.encode("utf-8")) <= max_bytes:
        return snapshot

    # 按优先级截断：先减 interactive_elements，再减 form_fields
    # active_dialogs 最后截断（最重要）
    while len(serialized.encode("utf-8")) > max_bytes:
        if len(snapshot.interactive_elements_summary) > 5:
            snapshot.interactive_elements_summary = snapshot.interactive_elements_summary[
                : len(snapshot.interactive_elements_summary) // 2
            ]
            snapshot.truncated = True
        elif len(snapshot.form_fields) > 5:
            snapshot.form_fields = snapshot.form_fields[
                : len(snapshot.form_fields) // 2
            ]
            snapshot.truncated = True
        elif len(snapshot.active_dialogs) > 1:
            snapshot.active_dialogs = snapshot.active_dialogs[:1]
            snapshot.truncated = True
        else:
            # 最后手段：清空所有列表
            snapshot.interactive_elements_summary = []
            snapshot.form_fields = []
            snapshot.truncated = True
            break
        serialized = snapshot.model_dump_json()

    return snapshot
