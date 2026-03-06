# server/app/avatar/skills/core/net.py

from __future__ import annotations

import httpx
import json
import logging
from typing import Optional, Any, Dict
from pydantic import Field

from ..base import BaseSkill, SkillSpec, SideEffect, SkillRiskLevel
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext

logger = logging.getLogger(__name__)


def _parse_json_or_none(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


# ── net.get ───────────────────────────────────────────────────────────────────

class NetGetInput(SkillInput):
    url: str = Field(..., description="Target URL")
    params_json: Optional[str] = Field(None, description="Query parameters as JSON string")
    headers_json: Optional[str] = Field(None, description="HTTP headers as JSON string")
    timeout: int = Field(30, description="Timeout in seconds")

class NetGetOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Response body")
    url: str
    status_code: int = 0
    ok: bool = False
    headers: Dict[str, str] = {}
    text: str = ""

@register_skill
class NetGetSkill(BaseSkill[NetGetInput, NetGetOutput]):
    spec = SkillSpec(
        name="net.get",
        description="Send HTTP GET request. 发送HTTP GET请求。",
        input_model=NetGetInput,
        output_model=NetGetOutput,
        side_effects={SideEffect.NETWORK},
        risk_level=SkillRiskLevel.READ,
        aliases=["http_get", "fetch", "get_url"],
    )

    async def run(self, ctx: SkillContext, params: NetGetInput) -> NetGetOutput:
        if ctx.dry_run:
            return NetGetOutput(success=True, message=f"[dry_run] GET {params.url}", url=params.url, status_code=200, ok=True, output="")

        try:
            async with httpx.AsyncClient(timeout=params.timeout) as client:
                resp = await client.get(
                    params.url,
                    params=_parse_json_or_none(params.params_json),
                    headers=_parse_json_or_none(params.headers_json),
                )
            text = resp.text[:50000] + ("\n...[truncated]" if len(resp.text) > 50000 else "")
            return NetGetOutput(success=resp.is_success, message=f"Status: {resp.status_code}",
                                url=params.url, status_code=resp.status_code, ok=resp.is_success,
                                headers=dict(resp.headers), text=text, output=text)
        except Exception as e:
            return NetGetOutput(success=False, message=str(e), url=params.url)


# ── net.post ──────────────────────────────────────────────────────────────────

class NetPostInput(SkillInput):
    url: str = Field(..., description="Target URL")
    body_json: Optional[str] = Field(None, description="Request body as JSON string")
    headers_json: Optional[str] = Field(None, description="HTTP headers as JSON string")
    timeout: int = Field(30, description="Timeout in seconds")

class NetPostOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Response body")
    url: str
    status_code: int = 0
    ok: bool = False
    headers: Dict[str, str] = {}
    text: str = ""

@register_skill
class NetPostSkill(BaseSkill[NetPostInput, NetPostOutput]):
    spec = SkillSpec(
        name="net.post",
        description="Send HTTP POST request with JSON body. 发送HTTP POST请求。",
        input_model=NetPostInput,
        output_model=NetPostOutput,
        side_effects={SideEffect.NETWORK},
        risk_level=SkillRiskLevel.WRITE,
        aliases=["http_post", "post_url"],
    )

    async def run(self, ctx: SkillContext, params: NetPostInput) -> NetPostOutput:
        if ctx.dry_run:
            return NetPostOutput(success=True, message=f"[dry_run] POST {params.url}", url=params.url, status_code=200, ok=True, output="")

        try:
            async with httpx.AsyncClient(timeout=params.timeout) as client:
                resp = await client.post(
                    params.url,
                    json=_parse_json_or_none(params.body_json),
                    headers=_parse_json_or_none(params.headers_json),
                )
            text = resp.text[:50000] + ("\n...[truncated]" if len(resp.text) > 50000 else "")
            return NetPostOutput(success=resp.is_success, message=f"Status: {resp.status_code}",
                                 url=params.url, status_code=resp.status_code, ok=resp.is_success,
                                 headers=dict(resp.headers), text=text, output=text)
        except Exception as e:
            return NetPostOutput(success=False, message=str(e), url=params.url)
