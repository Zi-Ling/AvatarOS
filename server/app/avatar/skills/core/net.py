# server/app/avatar/skills/core/net.py

from __future__ import annotations

import hashlib
import httpx
import json
import logging
import mimetypes
import re
from pathlib import Path
from typing import Optional, Any, Dict
from pydantic import Field

from ..base import BaseSkill, SkillSpec, SideEffect, SkillRiskLevel
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext
from app.avatar.runtime.graph.models.output_contract import SkillOutputContract, ValueKind, TransportMode

logger = logging.getLogger(__name__)

# 安全阈值：超过此大小的响应体不直接注入 outputs
_SAFE_TEXT_BYTES = 32 * 1024  # 32KB
_PREVIEW_BYTES = 512

# 可安全直读的 MIME 前缀
_SAFE_TEXT_MIMES = (
    "text/plain", "text/html", "text/csv", "text/markdown",
    "application/json", "application/xml", "application/x-www-form-urlencoded",
)

# net.download 允许的 MIME 类型（防止下载可执行文件）
_ALLOWED_DOWNLOAD_MIMES = (
    "image/", "video/", "audio/", "application/pdf",
    "application/zip", "application/x-zip", "application/gzip",
    "application/octet-stream", "text/", "application/json",
    "application/xml", "application/csv",
)

_MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024  # 200MB


def _parse_json_or_none(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _is_safe_text_mime(content_type: str) -> bool:
    ct = content_type.lower().split(";")[0].strip()
    return any(ct.startswith(m) for m in _SAFE_TEXT_MIMES)


def _is_allowed_download_mime(content_type: str) -> bool:
    ct = content_type.lower().split(";")[0].strip()
    return any(ct.startswith(m) for m in _ALLOWED_DOWNLOAD_MIMES)


def _sanitize_filename(name: str) -> str:
    """清洗文件名，防止路径穿越"""
    name = re.sub(r'[^\w\-_\. ]', '_', name)
    name = name.lstrip('.')
    return name[:128] or "download"


# ── net.get ───────────────────────────────────────────────────────────────────

class NetGetInput(SkillInput):
    url: str = Field(..., description="Target URL")
    params_json: Optional[str] = Field(None, description="Query parameters as JSON string")
    headers_json: Optional[str] = Field(None, description="HTTP headers as JSON string")
    timeout: int = Field(30, description="Timeout in seconds")

class NetGetOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Response body (text only, safe size)")
    url: str
    status_code: int = 0
    ok: bool = False
    content_type: str = ""
    size: int = 0
    # 安全直读时填充
    text: str = ""
    # 超限/二进制时填充
    truncated: bool = False
    body_preview: Optional[str] = None
    suggested_action: Optional[str] = None

@register_skill
class NetGetSkill(BaseSkill[NetGetInput, NetGetOutput]):
    spec = SkillSpec(
        name="net.get",
        description=(
            "Send HTTP GET request. Returns full body only for small text responses (<32KB). "
            "For large/binary content, returns preview + suggested_action (use net.download). "
            "发送HTTP GET请求，小文本直接返回，大内容/二进制只返回预览和建议操作。"
        ),
        input_model=NetGetInput,
        output_model=NetGetOutput,
        side_effects={SideEffect.NETWORK},
        risk_level=SkillRiskLevel.READ,
        aliases=["http_get", "fetch", "get_url"],
        tags=["fetch", "get", "download", "request", "获取", "下载", "请求"],
        output_contract=SkillOutputContract(value_kind=ValueKind.TEXT, transport_mode=TransportMode.INLINE),
    )

    async def run(self, ctx: SkillContext, params: NetGetInput) -> NetGetOutput:
        if ctx.dry_run:
            return NetGetOutput(
                success=True, message=f"[dry_run] GET {params.url}",
                url=params.url, status_code=200, ok=True, output="",
            )

        try:
            async with httpx.AsyncClient(timeout=params.timeout, follow_redirects=True, max_redirects=5) as client:
                resp = await client.get(
                    params.url,
                    params=_parse_json_or_none(params.params_json),
                    headers=_parse_json_or_none(params.headers_json),
                )

            content_type = resp.headers.get("content-type", "")
            size = int(resp.headers.get("content-length", 0)) or len(resp.content)
            is_safe_mime = _is_safe_text_mime(content_type)
            is_small = size <= _SAFE_TEXT_BYTES

            if is_safe_mime and is_small:
                # 安全直读路径
                text = resp.text
                return NetGetOutput(
                    success=resp.is_success,
                    message=f"Status: {resp.status_code}",
                    url=str(resp.url),
                    status_code=resp.status_code,
                    ok=resp.is_success,
                    content_type=content_type,
                    size=size,
                    text=text,
                    output=text,
                    truncated=False,
                )
            else:
                # 超限或二进制：只返回预览 + 建议
                try:
                    preview = resp.text[:_PREVIEW_BYTES]
                except Exception:
                    preview = repr(resp.content[:_PREVIEW_BYTES])

                if not is_safe_mime:
                    action = f"Use net.download to save this {content_type or 'binary'} file to workspace"
                else:
                    action = f"Use net.download to save this large response ({size} bytes) to workspace, then fs.read or python.run to process"

                return NetGetOutput(
                    success=resp.is_success,
                    message=f"Status: {resp.status_code} — content too large or binary, use net.download",
                    url=str(resp.url),
                    status_code=resp.status_code,
                    ok=resp.is_success,
                    content_type=content_type,
                    size=size,
                    truncated=True,
                    body_preview=preview,
                    suggested_action=action,
                    output=None,
                )

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
    content_type: str = ""
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
        tags=["post", "send", "submit", "发送", "提交"],
        output_contract=SkillOutputContract(value_kind=ValueKind.TEXT, transport_mode=TransportMode.INLINE),
    )

    async def run(self, ctx: SkillContext, params: NetPostInput) -> NetPostOutput:
        if ctx.dry_run:
            return NetPostOutput(
                success=True, message=f"[dry_run] POST {params.url}",
                url=params.url, status_code=200, ok=True, output="",
            )

        try:
            async with httpx.AsyncClient(timeout=params.timeout, follow_redirects=True, max_redirects=5) as client:
                resp = await client.post(
                    params.url,
                    json=_parse_json_or_none(params.body_json),
                    headers=_parse_json_or_none(params.headers_json),
                )
            content_type = resp.headers.get("content-type", "")
            text = resp.text[:50000] + ("\n...[truncated]" if len(resp.text) > 50000 else "")
            return NetPostOutput(
                success=resp.is_success,
                message=f"Status: {resp.status_code}",
                url=str(resp.url),
                status_code=resp.status_code,
                ok=resp.is_success,
                content_type=content_type,
                text=text,
                output=text,
            )
        except Exception as e:
            return NetPostOutput(success=False, message=str(e), url=params.url)


# ── net.download ──────────────────────────────────────────────────────────────

class NetDownloadInput(SkillInput):
    url: str = Field(..., description="URL to download")
    filename: Optional[str] = Field(None, description="Save as filename (auto-detected if omitted)")
    headers_json: Optional[str] = Field(None, description="HTTP headers as JSON string")
    timeout: int = Field(120, description="Timeout in seconds")

class NetDownloadOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Saved file path")
    file_path: str = ""
    filename: str = ""
    mime_type: str = ""
    size: int = 0
    sha256: str = ""
    url: str = ""

@register_skill
class NetDownloadSkill(BaseSkill[NetDownloadInput, NetDownloadOutput]):
    spec = SkillSpec(
        name="net.download",
        description=(
            "Download a file from URL and save to workspace. "
            "Returns file_path, mime_type, size, sha256. "
            "Never puts binary content in outputs — use this for images, PDFs, ZIPs, large files. "
            "从URL下载文件到workspace，返回文件路径和元信息，不把二进制内容放入outputs。"
        ),
        input_model=NetDownloadInput,
        output_model=NetDownloadOutput,
        side_effects={SideEffect.NETWORK, SideEffect.FS},
        risk_level=SkillRiskLevel.WRITE,
        aliases=["download_file", "http_download", "fetch_file"],
        tags=["download", "fetch", "save", "下载", "获取"],
        output_contract=SkillOutputContract(value_kind=ValueKind.PATH, transport_mode=TransportMode.REF),
    )

    async def run(self, ctx: SkillContext, params: NetDownloadInput) -> NetDownloadOutput:
        if ctx.dry_run:
            return NetDownloadOutput(
                success=True, message=f"[dry_run] Would download {params.url}",
                url=params.url, file_path="<dry_run>", filename="<dry_run>",
            )

        if not ctx.base_path:
            return NetDownloadOutput(
                success=False, message="base_path not set — cannot save file", url=params.url,
            )

        try:
            async with httpx.AsyncClient(
                timeout=params.timeout, follow_redirects=True, max_redirects=5
            ) as client:
                async with client.stream("GET", params.url,
                                         headers=_parse_json_or_none(params.headers_json)) as resp:
                    if not resp.is_success:
                        return NetDownloadOutput(
                            success=False,
                            message=f"HTTP {resp.status_code}",
                            url=str(resp.url),
                        )

                    content_type = resp.headers.get("content-type", "application/octet-stream")

                    # MIME 白名单检查
                    if not _is_allowed_download_mime(content_type):
                        return NetDownloadOutput(
                            success=False,
                            message=f"MIME type not allowed for download: {content_type}",
                            url=str(resp.url),
                        )

                    # 确定文件名
                    if params.filename:
                        filename = _sanitize_filename(params.filename)
                    else:
                        # 从 Content-Disposition 或 URL 推断
                        cd = resp.headers.get("content-disposition", "")
                        fname_match = re.search(r'filename[^;=\n]*=(["\']?)([^"\'\n;]+)\1', cd)
                        if fname_match:
                            filename = _sanitize_filename(fname_match.group(2).strip())
                        else:
                            url_path = str(resp.url).split("?")[0].rstrip("/")
                            url_basename = url_path.split("/")[-1]
                            if url_basename:
                                filename = _sanitize_filename(url_basename)
                            else:
                                # fallback: url hash 保证唯一性，避免多次下载不同 URL 都叫 "download"
                                url_hash = hashlib.sha256(str(resp.url).encode()).hexdigest()[:12]
                                ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ""
                                filename = f"download_{url_hash}{ext}"
                            # 补充扩展名（仅当文件名没有扩展名时）
                            if "." not in filename:
                                ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ""
                                filename += ext

                    # base_path 由 GraphExecutor 根据 skill 类型决定：
                    # net.download → session_workspace.root（容器挂载目录）
                    # 其他 skill → user_workspace
                    save_path = ctx.base_path / filename
                    save_path.parent.mkdir(parents=True, exist_ok=True)

                    # Streaming 写盘 + sha256 + 大小限制
                    hasher = hashlib.sha256()
                    total = 0
                    with open(save_path, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=65536):
                            total += len(chunk)
                            if total > _MAX_DOWNLOAD_BYTES:
                                save_path.unlink(missing_ok=True)
                                return NetDownloadOutput(
                                    success=False,
                                    message=f"File exceeds max download size ({_MAX_DOWNLOAD_BYTES // 1024 // 1024}MB)",
                                    url=str(resp.url),
                                )
                            hasher.update(chunk)
                            f.write(chunk)

            sha256 = hasher.hexdigest()

            return NetDownloadOutput(
                success=True,
                message=f"Downloaded {total} bytes → {filename}",
                url=str(resp.url),
                file_path=str(save_path),
                filename=filename,
                mime_type=content_type,
                size=total,
                sha256=sha256,
                output=str(save_path),
            )

        except Exception as e:
            return NetDownloadOutput(success=False, message=str(e), url=params.url)
