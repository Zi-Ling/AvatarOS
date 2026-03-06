# server/app/avatar/skills/core/net_skill.py

from __future__ import annotations

import httpx
import json
import logging
from typing import Optional, Any, Dict
from pydantic import Field

from ..base import BaseSkill, SkillSpec, SkillCategory, SkillPermission, SkillMetadata, SkillDomain, SkillCapability, SkillRiskLevel
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext

logger = logging.getLogger(__name__)

def _parse_json_or_none(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise ValueError("JSON must be an object")
        return obj
    except Exception:
        return None


# ============================================================================
# net.get - HTTP GET 请求
# ============================================================================

class NetGetInput(SkillInput):
    url: str = Field(..., description="Target URL")
    params_json: Optional[str] = Field(None, description="Query parameters as JSON string")
    headers_json: Optional[str] = Field(None, description="HTTP headers as JSON string")
    timeout: int = Field(30, description="Timeout in seconds")

class NetGetOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Primary output: response body")
    url: str
    status_code: int = 0
    ok: bool = False
    headers: Dict[str, str] = {}
    text: str = ""

@register_skill
class NetGetSkill(BaseSkill[NetGetInput, NetGetOutput]):
    spec = SkillSpec(
        name="net.get",
        api_name="net.get",
        aliases=["http_get", "fetch", "get_url"],
        description="Send HTTP GET request. 发送HTTP GET请求。",
        category=SkillCategory.WEB,
        input_model=NetGetInput,
        output_model=NetGetOutput,
        
        meta=SkillMetadata(
            domain=SkillDomain.WEB,
            capabilities={SkillCapability.READ},
            risk_level=SkillRiskLevel.READ,
            priority=10,  # 核心技能
        ),
        
        synonyms=["http get", "fetch url", "get request", "HTTP请求", "获取网页"],
        
        examples=[
            {"description": "Get webpage", "params": {"url": "https://example.com"}},
            {"description": "Get with params", "params": {"url": "https://api.example.com/search", "params_json": '{"q": "test"}'}},
        ],
        
        permissions=[SkillPermission(name="net_access", description="Access external network")],
        tags=["http", "web", "get", "网络", "请求"]
    )

    async def run(self, ctx: SkillContext, params: NetGetInput) -> NetGetOutput:
        if ctx.dry_run:
            return NetGetOutput(
                success=True,
                message=f"[dry_run] GET {params.url}",
                url=params.url,
                status_code=200,
                ok=True,
                output=""
            )

        query_params = _parse_json_or_none(params.params_json)
        headers = _parse_json_or_none(params.headers_json)

        try:
            async with httpx.AsyncClient(timeout=params.timeout) as client:
                resp = await client.get(params.url, params=query_params, headers=headers)
            
            text = resp.text
            if len(text) > 50000:
                text = text[:50000] + "\n...[truncated]"
            
            return NetGetOutput(
                success=resp.is_success,
                message=f"Status: {resp.status_code}",
                url=params.url,
                status_code=resp.status_code,
                ok=resp.is_success,
                headers=dict(resp.headers),
                text=text,
                output=text
            )
        except Exception as e:
            return NetGetOutput(
                success=False,
                message=str(e),
                url=params.url,
                output=None
            )


# ============================================================================
# net.post - HTTP POST 请求
# ============================================================================

class NetPostInput(SkillInput):
    url: str = Field(..., description="Target URL")
    body_json: Optional[str] = Field(None, description="Request body as JSON string")
    headers_json: Optional[str] = Field(None, description="HTTP headers as JSON string")
    timeout: int = Field(30, description="Timeout in seconds")

class NetPostOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Primary output: response body")
    url: str
    status_code: int = 0
    ok: bool = False
    headers: Dict[str, str] = {}
    text: str = ""

@register_skill
class NetPostSkill(BaseSkill[NetPostInput, NetPostOutput]):
    spec = SkillSpec(
        name="net.post",
        api_name="net.post",
        aliases=["http_post", "post_url"],
        description="Send HTTP POST request with JSON body. 发送HTTP POST请求。",
        category=SkillCategory.WEB,
        input_model=NetPostInput,
        output_model=NetPostOutput,
        
        meta=SkillMetadata(
            domain=SkillDomain.WEB,
            capabilities={SkillCapability.WRITE},
            risk_level=SkillRiskLevel.WRITE,
            priority=10,
        ),
        
        synonyms=["http post", "post request", "send data", "POST请求", "发送数据"],
        
        examples=[
            {"description": "Post JSON data", "params": {"url": "https://api.example.com/data", "body_json": '{"key": "value"}'}},
        ],
        
        permissions=[SkillPermission(name="net_access", description="Access external network")],
        tags=["http", "web", "post", "网络", "请求"]
    )

    async def run(self, ctx: SkillContext, params: NetPostInput) -> NetPostOutput:
        if ctx.dry_run:
            return NetPostOutput(
                success=True,
                message=f"[dry_run] POST {params.url}",
                url=params.url,
                status_code=200,
                ok=True,
                output=""
            )

        body = _parse_json_or_none(params.body_json)
        headers = _parse_json_or_none(params.headers_json)

        try:
            async with httpx.AsyncClient(timeout=params.timeout) as client:
                resp = await client.post(params.url, json=body, headers=headers)
            
            text = resp.text
            if len(text) > 50000:
                text = text[:50000] + "\n...[truncated]"
            
            return NetPostOutput(
                success=resp.is_success,
                message=f"Status: {resp.status_code}",
                url=params.url,
                status_code=resp.status_code,
                ok=resp.is_success,
                headers=dict(resp.headers),
                text=text,
                output=text
            )
        except Exception as e:
            return NetPostOutput(
                success=False,
                message=str(e),
                url=params.url,
                output=None
            )
