"""
web.search — 开放世界搜索 skill（多 Provider 架构）

Provider 优先级（自动选择）：
1. 商业 API（配了 key 就用）：Brave > Google CSE > Tavily
2. SearXNG（自托管，配了 URL 就用）
3. DuckDuckGo（兜底，永远可用）

每个 provider 失败时自动降级到下一个。
"""

from __future__ import annotations

import logging
import os
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

import httpx
from pydantic import Field

from ..base import BaseSkill, SkillSpec, SideEffect, SkillRiskLevel
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext

logger = logging.getLogger(__name__)

_DEFAULT_MAX_RESULTS = 5
_SEARCH_TIMEOUT = 15  # seconds


# ── 搜索结果模型 ─────────────────────────────────────────────────────────────

class WebSearchInput(SkillInput):
    query: str = Field(..., description="Search query string")
    max_results: int = Field(
        _DEFAULT_MAX_RESULTS,
        description="Maximum number of results to return (1-10)",
        ge=1, le=10,
    )


class WebSearchOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Formatted search results text")
    query: str = ""
    source: str = ""  # provider name
    result_count: int = 0
    results: List[Dict[str, Any]] = Field(default_factory=list)


# ── Provider 基类 ────────────────────────────────────────────────────────────

class SearchProvider(ABC):
    """统一搜索 provider 接口"""
    name: str = ""

    @abstractmethod
    def is_available(self) -> bool:
        """检查 provider 是否可用（有 key / URL 可达）"""
        ...

    @abstractmethod
    async def search(
        self, query: str, max_results: int
    ) -> List[Dict[str, Any]]:
        """执行搜索，返回统一格式的结果列表。
        每条: {title, url, snippet, published_at}
        """
        ...


# ── Brave Search Provider ────────────────────────────────────────────────────

class BraveProvider(SearchProvider):
    name = "brave"

    def __init__(self) -> None:
        self._api_key = self._get_key()

    @staticmethod
    def _get_key() -> str:
        try:
            from app.core.config import config
            if config.brave_api_key:
                return config.brave_api_key
        except Exception:
            pass
        return os.environ.get("BRAVE_API_KEY", "")

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=_SEARCH_TIMEOUT) as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": max_results, "freshness": "pd"},
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": self._api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("web", {}).get("results", [])[:max_results]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("description", ""),
                "published_at": item.get("page_age"),
            })
        return results


# ── Google Custom Search Provider ────────────────────────────────────────────

class GoogleCSEProvider(SearchProvider):
    name = "google"

    def __init__(self) -> None:
        self._api_key, self._cx = self._get_keys()

    @staticmethod
    def _get_keys() -> tuple:
        api_key, cx = "", ""
        try:
            from app.core.config import config
            api_key = config.google_cse_key or ""
            cx = config.google_cse_id or ""
        except Exception:
            pass
        api_key = api_key or os.environ.get("GOOGLE_CSE_KEY", "")
        cx = cx or os.environ.get("GOOGLE_CSE_ID", "")
        return api_key, cx

    def is_available(self) -> bool:
        return bool(self._api_key and self._cx)

    async def search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=_SEARCH_TIMEOUT) as client:
            resp = await client.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "key": self._api_key,
                    "cx": self._cx,
                    "q": query,
                    "num": min(max_results, 10),
                    "dateRestrict": "d1",  # 过去 1 天
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("items", [])[:max_results]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "published_at": None,
            })
        return results


# ── Tavily Provider ──────────────────────────────────────────────────────────

class TavilyProvider(SearchProvider):
    name = "tavily"

    def __init__(self) -> None:
        self._api_key = self._get_key()

    @staticmethod
    def _get_key() -> str:
        try:
            from app.core.config import config
            if config.tavily_api_key:
                return config.tavily_api_key
            # 兼容旧配置
            if config.web_search_api_key:
                return config.web_search_api_key
        except Exception:
            pass
        return os.environ.get("TAVILY_API_KEY", "") or os.environ.get("WEB_SEARCH_API_KEY", "")

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=_SEARCH_TIMEOUT) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self._api_key,
                    "query": query,
                    "max_results": max_results,
                    "include_answer": False,
                    "include_raw_content": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("results", [])[:max_results]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", ""),
                "published_at": item.get("published_date"),
            })
        return results


# ── SearXNG Provider ─────────────────────────────────────────────────────────

class SearXNGProvider(SearchProvider):
    name = "searxng"

    def __init__(self) -> None:
        self._url = self._get_url()
        self._healthy: Optional[bool] = None  # 缓存健康状态

    @staticmethod
    def _get_url() -> str:
        try:
            from app.core.config import config
            if config.searxng_url:
                return config.searxng_url.rstrip("/")
        except Exception:
            pass
        return os.environ.get("SEARXNG_URL", "").rstrip("/")

    def is_available(self) -> bool:
        return bool(self._url)

    async def _health_check(self) -> bool:
        """首次调用时做健康检查，结果缓存"""
        if self._healthy is not None:
            return self._healthy
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(
                    f"{self._url}/search",
                    params={"q": "ping", "format": "json"},
                )
                self._healthy = resp.status_code == 200
        except Exception:
            self._healthy = False
        if not self._healthy:
            logger.warning(f"[SearXNG] Health check failed for {self._url}")
        return self._healthy

    async def search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        if not await self._health_check():
            return []

        async with httpx.AsyncClient(timeout=_SEARCH_TIMEOUT) as client:
            resp = await client.get(
                f"{self._url}/search",
                params={
                    "q": query,
                    "format": "json",
                    "time_range": "day",
                    "engines": "google,bing,duckduckgo",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("results", [])[:max_results]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", ""),
                "published_at": item.get("publishedDate"),
            })
        return results


# ── DuckDuckGo Provider（兜底）────────────────────────────────────────────────

class DuckDuckGoProvider(SearchProvider):
    name = "duckduckgo"

    def is_available(self) -> bool:
        return True  # 永远可用

    async def search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        async with httpx.AsyncClient(
            timeout=_SEARCH_TIMEOUT, follow_redirects=True, headers=headers
        ) as client:
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
            )
            resp.raise_for_status()
            html = resp.text

        return self._parse_html(html, max_results)

    @staticmethod
    def _parse_html(html: str, max_results: int) -> List[Dict[str, Any]]:
        results = []
        result_blocks = re.findall(
            r'<a[^>]+class="result__a"[^>]+href="([^"]*)"[^>]*>(.*?)</a>',
            html, re.DOTALL,
        )
        snippet_blocks = re.findall(
            r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
            html, re.DOTALL,
        )
        for i, (url, title_html) in enumerate(result_blocks[:max_results]):
            title = re.sub(r"<[^>]+>", "", title_html).strip()
            snippet = ""
            if i < len(snippet_blocks):
                snippet = re.sub(r"<[^>]+>", "", snippet_blocks[i]).strip()
            real_url = url
            ud_match = re.search(r"uddg=([^&]+)", url)
            if ud_match:
                real_url = unquote(ud_match.group(1))
            if title and real_url:
                results.append({
                    "title": title,
                    "url": real_url,
                    "snippet": snippet,
                    "published_at": None,
                })
        return results


# ── Provider Router ──────────────────────────────────────────────────────────

class ProviderRouter:
    """按优先级选择可用的搜索 provider，失败自动降级。"""

    def __init__(self) -> None:
        # 优先级：商业 API > SearXNG > DuckDuckGo
        self._providers: List[SearchProvider] = [
            BraveProvider(),
            GoogleCSEProvider(),
            TavilyProvider(),
            SearXNGProvider(),
            DuckDuckGoProvider(),
        ]
        self._log_available_providers()

    def _log_available_providers(self) -> None:
        available = [p.name for p in self._providers if p.is_available()]
        logger.info(f"[web.search] Available providers: {available}")

    async def search(
        self, query: str, max_results: int
    ) -> tuple:
        """返回 (results, source, errors)"""
        errors: List[str] = []
        for provider in self._providers:
            if not provider.is_available():
                continue
            try:
                results = await provider.search(query, max_results)
                if results:
                    logger.info(
                        f"[web.search] {provider.name} returned "
                        f"{len(results)} results for: {query}"
                    )
                    return results, provider.name, errors
                else:
                    logger.info(
                        f"[web.search] {provider.name} returned 0 results "
                        f"for: {query}, trying next"
                    )
            except Exception as e:
                msg = f"{provider.name}: {str(e)[:100]}"
                errors.append(msg)
                logger.warning(
                    f"[web.search] {provider.name} failed: {e}, trying next"
                )
        return [], "none", errors


# 全局单例（provider 配置在进程生命周期内不变）
_router: Optional[ProviderRouter] = None


def _get_router() -> ProviderRouter:
    global _router
    if _router is None:
        _router = ProviderRouter()
    return _router


def _format_results_text(
    query: str, results: List[Dict[str, Any]], source: str
) -> str:
    if not results:
        return f"No results found for: {query}"
    lines = [f'Search results for "{query}" (via {source}):']
    for i, r in enumerate(results, 1):
        lines.append(f"\n[{i}] {r['title']}")
        lines.append(f"    URL: {r['url']}")
        if r.get("snippet"):
            lines.append(f"    {r['snippet'][:300]}")
        if r.get("published_at"):
            lines.append(f"    Published: {r['published_at']}")
    return "\n".join(lines)


# ── Skill 定义 ────────────────────────────────────────────────────────────────

@register_skill
class WebSearchSkill(BaseSkill[WebSearchInput, WebSearchOutput]):
    spec = SkillSpec(
        name="web.search",
        description=(
            "Search the web for information. Returns structured results with "
            "title, URL, snippet. Supports multiple search backends with "
            "automatic fallback. "
            "搜索互联网信息，返回结构化结果（标题、URL、摘要）。"
        ),
        input_model=WebSearchInput,
        output_model=WebSearchOutput,
        side_effects={SideEffect.NETWORK},
        risk_level=SkillRiskLevel.READ,
        aliases=["web_search", "search_web", "internet_search"],
    )

    async def run(self, ctx: SkillContext, params: WebSearchInput) -> WebSearchOutput:
        if ctx.dry_run:
            return WebSearchOutput(
                success=True,
                message=f"[dry_run] Would search: {params.query}",
                query=params.query,
                source="dry_run",
                output="[dry_run]",
            )

        query = params.query.strip()
        if not query:
            return WebSearchOutput(
                success=False, message="Empty search query", query=query,
            )

        max_results = min(max(params.max_results, 1), 10)
        router = _get_router()
        results, source, errors = await router.search(query, max_results)

        if not results:
            error_detail = "; ".join(errors) if errors else "no results"
            return WebSearchOutput(
                success=True,
                message=f"No results found for: {query} ({error_detail})",
                query=query,
                source=source,
                result_count=0,
                results=[],
                output=f"No results found for: {query}",
            )

        formatted = _format_results_text(query, results, source)
        return WebSearchOutput(
            success=True,
            message=f"Found {len(results)} results via {source}",
            query=query,
            source=source,
            result_count=len(results),
            results=results,
            output=formatted,
        )
