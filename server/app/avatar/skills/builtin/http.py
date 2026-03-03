# app/avatar/skills/builtin/http.py

from __future__ import annotations

import httpx
import json
from typing import Optional, Any, Dict
from pydantic import Field

from ..base import BaseSkill, SkillSpec, SkillCategory, SkillPermission, SkillMetadata, SkillDomain, SkillCapability
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext


def _parse_json_or_none(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw: return None
    try:
        obj = json.loads(raw)
        if not isinstance(obj, dict): raise ValueError("JSON must be an object")
        return obj
    except Exception:
        return None


# ============================================================================
# http.get
# ============================================================================

class HttpGetInput(SkillInput):
    url: str = Field(..., description="Target URL.")
    params_json: Optional[str] = Field(None, description="Optional JSON object string for query parameters.")
    headers_json: Optional[str] = Field(None, description="Optional JSON object string for HTTP headers.")
    timeout: int = Field(30, description="Timeout in seconds.")

class HttpGetOutput(SkillOutput):
    url: str
    status_code: int = 0
    ok: bool = False
    headers: Dict[str, str] = {}
    text: str = ""

@register_skill
class HttpGetSkill(BaseSkill[HttpGetInput, HttpGetOutput]):
    spec = SkillSpec(
        name="http.get",
        api_name="http.get",
        aliases=["web.get", "request.get", "fetch"],
        description="Send an HTTP GET request. 发送HTTP GET请求。",
        category=SkillCategory.WEB,
        input_model=HttpGetInput,
        output_model=HttpGetOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.WEB,
            capabilities={SkillCapability.READ},
            risk_level="normal"
        ),
        
        synonyms=[
            "fetch url",
            "get request",
            "http request",
            "获取网页",
            "发送请求",
            "访问URL"
        ],
        examples=[
            {"description": "Get webpage", "params": {"url": "https://example.com"}},
            {"description": "Get with query params", "params": {"url": "https://api.example.com/search", "params_json": '{"q": "test"}'}}
        ],
        permissions=[SkillPermission(name="net_access", description="Access external network")],
        tags=["http", "web", "get", "HTTP", "请求", "网络"]
    )

    async def run(self, ctx: SkillContext, params: HttpGetInput) -> HttpGetOutput:
        if ctx.dry_run:
            return HttpGetOutput(
                success=True,
                message=f"[dry_run] GET {params.url}",
                url=params.url,
                status_code=200,
                ok=True
            )

        query_params = _parse_json_or_none(params.params_json)
        headers = _parse_json_or_none(params.headers_json)

        try:
            async with httpx.AsyncClient(timeout=params.timeout) as client:
                resp = await client.get(params.url, params=query_params, headers=headers)
            text = resp.text
            if len(text) > 50000: text = text[:50000] + "\n...[truncated]"
            
            return HttpGetOutput(
                success=resp.is_success,
                message=f"Status: {resp.status_code}",
                url=params.url,
                status_code=resp.status_code,
                ok=resp.is_success,
                headers=dict(resp.headers),
                text=text
            )
        except Exception as e:
            return HttpGetOutput(success=False, message=str(e), url=params.url)


# ============================================================================
# http.post
# ============================================================================

class HttpPostInput(SkillInput):
    url: str = Field(..., description="Target URL.")
    body_json: Optional[str] = Field(None, description="Optional JSON object string as POST body.")
    headers_json: Optional[str] = Field(None, description="Optional JSON object string for HTTP headers.")
    timeout: int = Field(30, description="Timeout in seconds.")

class HttpPostOutput(SkillOutput):
    url: str
    status_code: int = 0
    ok: bool = False
    headers: Dict[str, str] = {}
    text: str = ""

@register_skill
class HttpPostSkill(BaseSkill[HttpPostInput, HttpPostOutput]):
    spec = SkillSpec(
        name="http.post",
        api_name="http.post",
        aliases=["web.post", "request.post"],
        description="Send an HTTP POST request with JSON body. 发送HTTP POST请求。",
        category=SkillCategory.WEB,
        input_model=HttpPostInput,
        output_model=HttpPostOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.WEB,
            capabilities={SkillCapability.WRITE},
            risk_level="high"
        ),
        
        synonyms=[
            "post request",
            "send data",
            "submit form",
            "发送POST请求",
            "提交数据",
            "发送数据"
        ],
        examples=[
            {"description": "Post JSON data", "params": {"url": "https://api.example.com/data", "body_json": '{"key": "value"}'}}
        ],
        permissions=[SkillPermission(name="net_access", description="Access external network")],
        tags=["http", "web", "post", "HTTP", "POST", "请求", "发送"]
    )

    async def run(self, ctx: SkillContext, params: HttpPostInput) -> HttpPostOutput:
        if ctx.dry_run:
            return HttpPostOutput(
                success=True,
                message=f"[dry_run] POST {params.url}",
                url=params.url,
                status_code=200,
                ok=True
            )

        body = _parse_json_or_none(params.body_json)
        headers = _parse_json_or_none(params.headers_json)

        try:
            async with httpx.AsyncClient(timeout=params.timeout) as client:
                resp = await client.post(params.url, json=body, headers=headers)
            text = resp.text
            if len(text) > 50000: text = text[:50000] + "\n...[truncated]"
            
            return HttpPostOutput(
                success=resp.is_success,
                message=f"Status: {resp.status_code}",
                url=params.url,
                status_code=resp.status_code,
                ok=resp.is_success,
                headers=dict(resp.headers),
                text=text
            )
        except Exception as e:
            return HttpPostOutput(success=False, message=str(e), url=params.url)
