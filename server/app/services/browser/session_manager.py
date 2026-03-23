# server/app/services/browser/session_manager.py
"""三级会话模型生命周期管理：Session → Context → Page。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.services.browser.errors import SessionCapacityError, SessionNotFoundError
from app.services.browser.models import (
    BrowserAutomationConfig,
    BrowserContextHandle,
    BrowserErrorCode,
    ContextOptions,
    ContextSummary,
    PageHandle,
    PageSummary,
    ResourceQuota,
    SessionHandle,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return str(uuid.uuid4())


class SessionManager:
    """三级会话模型生命周期管理。"""

    def __init__(self, config: BrowserAutomationConfig | None = None):
        self._config = config or BrowserAutomationConfig()
        # 内存存储
        self._sessions: dict[str, SessionHandle] = {}
        self._contexts: dict[str, BrowserContextHandle] = {}
        self._pages: dict[str, PageHandle] = {}

    # ── create ────────────────────────────────────────────────────────

    async def create_session(
        self,
        config: BrowserAutomationConfig | None = None,
        workflow_instance_id: str | None = None,
    ) -> SessionHandle:
        cfg = config or self._config
        if len(self._sessions) >= cfg.max_concurrent_sessions:
            raise SessionCapacityError(
                f"Max concurrent sessions ({cfg.max_concurrent_sessions}) reached"
            )
        now = _now()
        session = SessionHandle(
            session_id=_uid(),
            workflow_instance_id=workflow_instance_id,
            created_at=now,
            last_active_at=now,
            browser_config={
                "headless": cfg.headless,
                "viewport_width": cfg.viewport_width,
                "viewport_height": cfg.viewport_height,
            },
            resource_quota=ResourceQuota(
                max_artifacts=cfg.max_artifacts_per_session,
                max_download_bytes=cfg.max_download_size_bytes,
            ),
        )
        self._sessions[session.session_id] = session
        return session

    async def create_context(
        self,
        session_id: str,
        context_options: ContextOptions | None = None,
    ) -> BrowserContextHandle:
        session = self._sessions.get(session_id)
        if not session:
            raise SessionNotFoundError(session_id)
        now = _now()
        ctx = BrowserContextHandle(
            context_id=_uid(),
            session_id=session_id,
            created_at=now,
        )
        self._contexts[ctx.context_id] = ctx
        session.context_ids.append(ctx.context_id)
        session.last_active_at = now
        return ctx

    async def create_page(self, context_id: str) -> PageHandle:
        ctx = self._contexts.get(context_id)
        if not ctx:
            raise SessionNotFoundError(f"Context not found: {context_id}")
        session = self._sessions.get(ctx.session_id)
        if not session:
            raise SessionNotFoundError(ctx.session_id)
        # 检查每会话最大 page 数
        total_pages = sum(
            1 for p in self._pages.values()
            if self._contexts.get(p.context_id, BrowserContextHandle(
                context_id="", session_id="", created_at=_now()
            )).session_id == ctx.session_id
        )
        if total_pages >= self._config.max_pages_per_session:
            raise SessionCapacityError(
                f"Max pages per session ({self._config.max_pages_per_session}) reached"
            )
        now = _now()
        page = PageHandle(
            page_id=_uid(),
            context_id=context_id,
            created_at=now,
        )
        self._pages[page.page_id] = page
        ctx.page_ids.append(page.page_id)
        session.last_active_at = now
        return page

    # ── get / destroy ─────────────────────────────────────────────────

    async def get_session(self, session_id: str) -> SessionHandle | None:
        return self._sessions.get(session_id)

    async def destroy_session(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if not session:
            return
        for cid in list(session.context_ids):
            await self._destroy_context_internal(cid)

    async def destroy_context(self, context_id: str) -> None:
        ctx = self._contexts.get(context_id)
        if not ctx:
            return
        session = self._sessions.get(ctx.session_id)
        if session and context_id in session.context_ids:
            session.context_ids.remove(context_id)
        await self._destroy_context_internal(context_id)

    async def _destroy_context_internal(self, context_id: str) -> None:
        ctx = self._contexts.pop(context_id, None)
        if not ctx:
            return
        for pid in list(ctx.page_ids):
            self._pages.pop(pid, None)

    async def destroy_page(self, page_id: str) -> None:
        page = self._pages.pop(page_id, None)
        if not page:
            return
        ctx = self._contexts.get(page.context_id)
        if ctx and page_id in ctx.page_ids:
            ctx.page_ids.remove(page_id)

    # ── list ──────────────────────────────────────────────────────────

    async def list_contexts(self, session_id: str) -> list[ContextSummary]:
        session = self._sessions.get(session_id)
        if not session:
            return []
        result = []
        for cid in session.context_ids:
            ctx = self._contexts.get(cid)
            if ctx:
                result.append(ContextSummary(
                    context_id=ctx.context_id,
                    page_count=len(ctx.page_ids),
                    created_at=ctx.created_at,
                ))
        return result

    async def list_pages(self, context_id: str) -> list[PageSummary]:
        ctx = self._contexts.get(context_id)
        if not ctx:
            return []
        now = _now()
        result = []
        for pid in ctx.page_ids:
            page = self._pages.get(pid)
            if page:
                idle = (now - page.created_at).total_seconds()
                result.append(PageSummary(
                    page_id=page.page_id,
                    url=page.url,
                    title=page.title,
                    idle_seconds=idle,
                ))
        return result

    # ── cleanup ───────────────────────────────────────────────────────

    async def cleanup_idle_sessions(self) -> list[str]:
        now = _now()
        timeout = self._config.session_idle_timeout_seconds
        to_remove: list[str] = []
        for sid, session in list(self._sessions.items()):
            idle = (now - session.last_active_at).total_seconds()
            if idle > timeout:
                to_remove.append(sid)
        for sid in to_remove:
            await self.destroy_session(sid)
        return to_remove
