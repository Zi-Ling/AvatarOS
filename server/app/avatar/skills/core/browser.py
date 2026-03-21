# server/app/avatar/skills/core/browser.py
"""
browser.run — 通用浏览器执行器 skill

设计原则：
- 单一 executor 型 skill，对标 python.run，不做功能 skill 集合
- LLM 生成受约束的 Playwright 脚本，skill 注入安全 preamble
- 多级回退提取链：DOM原语 → 容器HTML → 整页HTML
- artifact-first：截图/文件落盘，outputs 只返回轻量元信息
- per-task context 隔离，browser process 可复用
- 安全：沙箱内执行，stdout/stderr 截断，文件名清洗
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import Field

from ..base import BaseSkill, SkillSpec, SideEffect, SkillRiskLevel
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext
from app.avatar.runtime.graph.models.output_contract import SkillOutputContract, ValueKind, TransportMode

logger = logging.getLogger(__name__)

_MAX_STDOUT = 16 * 1024   # 16KB
_MAX_STDERR = 4 * 1024    # 4KB
_DEFAULT_TIMEOUT = 30_000  # ms
_DEFAULT_VIEWPORT = {"width": 1280, "height": 800}

# ── Browser Process Pool（模块级，process 复用，context 隔离）─────────────────

_browser_pool: Optional[Any] = None  # playwright Browser instance
_pool_lock = asyncio.Lock()


async def _get_browser():
    """获取或创建共享 browser process（Chromium headless）"""
    global _browser_pool
    async with _pool_lock:
        if _browser_pool is None or not _browser_pool.is_connected():
            try:
                from playwright.async_api import async_playwright
                pw = await async_playwright().start()
                _browser_pool = await pw.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                    ],
                )
                logger.info("[browser.run] Chromium browser process started")
            except Exception as e:
                logger.error(f"[browser.run] Failed to launch browser: {e}")
                raise
    return _browser_pool


# ── 安全 preamble（注入到每个脚本头部）──────────────────────────────────────

_PREAMBLE = textwrap.dedent("""
import asyncio, json, re, os, sys
from pathlib import Path
from playwright.async_api import Page, BrowserContext

# 安全约束：禁止访问 preamble 注入的内部变量
_WORKSPACE = Path(__file_workspace__)
_ARTIFACTS = []
_current_page = None  # 当前活跃页面，open_page() 后自动设置

# ── helper API（推荐 LLM 使用这些原语，而不是裸 Playwright）────────────────

async def open_page(url: str, wait_until: str = "domcontentloaded") -> Page:
    \"\"\"打开页面并等待加载，自动成为当前页\"\"\"
    global _current_page
    page = await _ctx.new_page()
    page.set_default_timeout(30000)
    await page.goto(url, wait_until=wait_until)
    # 等待页面稳定（处理弹窗/重定向）
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    _current_page = page
    return page

def _resolve_page(page=None) -> Page:
    \"\"\"解析 page 参数：优先用传入的，否则用当前页\"\"\"
    p = page if page is not None else _current_page
    if p is None:
        raise RuntimeError("No page available. Call open_page(url) first.")
    return p

async def wait_for(selector: str, page=None, timeout: int = 10000):
    \"\"\"等待元素出现（page 可省略，默认用当前页）\"\"\"
    await _resolve_page(page).wait_for_selector(selector, timeout=timeout)

async def click(selector: str, page=None):
    \"\"\"安全点击（等待可见后点击，page 可省略）\"\"\"
    p = _resolve_page(page)
    await p.locator(selector).wait_for(state="visible")
    await p.locator(selector).click()

async def fill(selector: str, value: str, page=None):
    \"\"\"填写表单字段（page 可省略）\"\"\"
    p = _resolve_page(page)
    await p.locator(selector).wait_for(state="visible")
    await p.locator(selector).fill(value)

async def press_key(key: str, page=None):
    \"\"\"按键（如 Enter），page 可省略\"\"\"
    await _resolve_page(page).keyboard.press(key)

async def extract_text(selector: str = "body", page=None) -> str:
    \"\"\"提取指定区域的纯文本（page 可省略）\"\"\"
    return await _resolve_page(page).locator(selector).inner_text()

async def extract_table(selector: str = "table", page=None) -> list:
    \"\"\"多级回退提取表格数据（page 可省略）\"\"\"
    p = _resolve_page(page)
    try:
        rows = await p.locator(f"{selector} tr").all()
        result = []
        for row in rows:
            cells = await row.locator("td, th").all_inner_texts()
            result.append(cells)
        return result
    except Exception:
        html = await p.locator(selector).inner_html()
        return [{"__raw_html__": html}]

async def extract_links(selector: str = "a", page=None) -> list:
    \"\"\"提取链接列表（page 可省略）\"\"\"
    p = _resolve_page(page)
    links = await p.locator(selector).all()
    result = []
    for link in links:
        href = await link.get_attribute("href")
        text = await link.inner_text()
        if href:
            result.append({"text": text.strip(), "href": href})
    return result

async def save_screenshot(filename: str = "", page=None) -> str:
    \"\"\"截图并保存到 workspace（page 可省略）\"\"\"
    import time as _time
    if not filename:
        filename = f"screenshot_{int(_time.time() * 1000)}.png"
    safe_name = re.sub(r'[^\\w\\-_\\.]', '_', filename)[:64]
    path = _WORKSPACE / safe_name
    await _resolve_page(page).screenshot(path=str(path), full_page=False)
    _ARTIFACTS.append(str(path))
    print(f"[artifact] {path}")
    return str(path)

async def save_full_screenshot(filename: str = "", page=None) -> str:
    \"\"\"全页截图（page 可省略）\"\"\"
    import time as _time
    if not filename:
        filename = f"screenshot_full_{int(_time.time() * 1000)}.png"
    safe_name = re.sub(r'[^\\w\\-_\\.]', '_', filename)[:64]
    path = _WORKSPACE / safe_name
    await _resolve_page(page).screenshot(path=str(path), full_page=True)
    _ARTIFACTS.append(str(path))
    print(f"[artifact] {path}")
    return str(path)

async def get_page_content(selector: str = None, page=None) -> str:
    \"\"\"获取页面文本内容（page 可省略）\"\"\"
    p = _resolve_page(page)
    if selector:
        try:
            return await p.locator(selector).inner_text()
        except Exception:
            pass
    return await p.locator("body").inner_text()

async def get_page_html(selector: str = None, page=None) -> str:
    \"\"\"获取页面 HTML（page 可省略）\"\"\"
    p = _resolve_page(page)
    if selector:
        return await p.locator(selector).inner_html()
    return await p.content()

async def save_file(content: str, filename: str, encoding: str = "utf-8") -> str:
    \"\"\"保存文本内容到 workspace 文件\"\"\"
    safe_name = re.sub(r'[^\\w\\-_\\.]', '_', filename)[:128]
    path = _WORKSPACE / safe_name
    path.write_text(content, encoding=encoding)
    _ARTIFACTS.append(str(path))
    print(f"[artifact] {path}")
    return str(path)

# ── 用户脚本从这里开始 ────────────────────────────────────────────────────────
""").strip()


# ── Skill 定义 ────────────────────────────────────────────────────────────────

class BrowserRunInput(SkillInput):
    script: str = Field(
        ...,
        description=(
            "Playwright async Python script. Use helper API — page parameter is OPTIONAL (auto-uses current page): "
            "open_page(url) → opens page and sets it as current; "
            "fill(selector, value) → fills input; "
            "click(selector) → clicks element; "
            "press_key(key) → presses keyboard key (e.g. 'Enter'); "
            "wait_for(selector) → waits for element; "
            "extract_text(selector?) → returns text; "
            "get_page_content(selector?) → returns body text; "
            "save_screenshot() → saves screenshot artifact; "
            "save_file(content, filename) → saves text file. "
            "Example: page = await open_page('https://baidu.com'); await fill('input#kw', 'query'); await press_key('Enter'); await wait_for('#content_left'); text = await extract_text('#content_left'); print(text). "
            "Do NOT call asyncio.run(). Do NOT define async def main(). Do NOT use 'if __name__==\"__main__\"'. "
            "Just write await statements directly. Use print() for all outputs."
        ),
    )
    start_url: Optional[str] = Field(None, description="Initial URL to open before script runs (optional)")
    timeout: int = Field(30, description="Total execution timeout in seconds")
    viewport_width: int = Field(1280, description="Viewport width in pixels")
    viewport_height: int = Field(800, description="Viewport height in pixels")
    session_profile: Optional[str] = Field(
        None,
        description="Reserved for future use: session profile ID for login state reuse. Currently disabled.",
    )


class BrowserRunOutput(SkillOutput):
    output: Optional[str] = Field(None, description="stdout from script (primary output)")
    stdout: str = ""
    stderr: str = ""
    artifacts: List[str] = Field(default_factory=list, description="Paths of files saved to workspace")
    final_url: Optional[str] = None
    page_title: Optional[str] = None
    truncated: bool = False


@register_skill
class BrowserRunSkill(BaseSkill[BrowserRunInput, BrowserRunOutput]):
    spec = SkillSpec(
        name="browser.run",
        description=(
            "Execute a Playwright script in a sandboxed browser. "
            "Use helper API (open_page, extract_table, save_screenshot, etc.) for stable extraction. "
            "Screenshots and files are saved to workspace as artifacts. "
            "Outputs: stdout, artifacts list, final_url, page_title. "
            "在沙箱浏览器中执行Playwright脚本，截图和文件落盘为artifact，outputs只返回轻量元信息。"
        ),
        input_model=BrowserRunInput,
        output_model=BrowserRunOutput,
        side_effects={SideEffect.NETWORK, SideEffect.FS, SideEffect.BROWSER},
        risk_level=SkillRiskLevel.EXECUTE,
        aliases=["browser_run", "playwright_run", "web_automation"],
        code_params={"script"},
        tags=["browse", "visit", "scrape", "浏览", "访问", "抓取", "截图"],
        output_contract=SkillOutputContract(value_kind=ValueKind.TEXT, transport_mode=TransportMode.INLINE),
    )

    async def run(self, ctx: SkillContext, params: BrowserRunInput) -> BrowserRunOutput:
        if ctx.dry_run:
            return BrowserRunOutput(
                success=True,
                message="[dry_run] Would execute browser script",
                stdout="[dry_run]",
                output="[dry_run]",
            )

        if not ctx.base_path:
            return BrowserRunOutput(
                success=False,
                message="base_path not set — cannot save artifacts",
            )

        workspace = ctx.base_path
        workspace.mkdir(parents=True, exist_ok=True)

        try:
            browser = await _get_browser()
        except Exception as e:
            return BrowserRunOutput(
                success=False,
                message=f"Browser unavailable: {e}. Ensure playwright is installed (pip install playwright && playwright install chromium).",
            )

        # per-task 独立 context（隔离 cookie/storage/页面状态）
        context = await browser.new_context(
            viewport={"width": params.viewport_width, "height": params.viewport_height},
            # session_profile 预留位，当前禁用
        )

        stdout_lines: List[str] = []
        stderr_lines: List[str] = []
        artifacts: List[str] = []
        final_url: Optional[str] = None
        page_title: Optional[str] = None

        try:
            # 构建完整脚本：preamble + 用户脚本包装在 async def _run()
            preamble = _PREAMBLE.replace("__file_workspace__", repr(str(workspace)))

            # 清理 LLM 可能生成的 asyncio.run(...) 调用（在已有 event loop 里会报错）
            cleaned_script = re.sub(r'^\s*asyncio\.run\s*\(.*\)\s*$', '', params.script, flags=re.MULTILINE)
            # 同时移除 if __name__ == "__main__": 块
            cleaned_script = re.sub(r'^\s*if\s+__name__\s*==\s*["\']__main__["\']\s*:.*', '', cleaned_script, flags=re.MULTILINE)

            # 用户脚本包装为无参 async def _main()，_ctx 通过 exec_globals 注入
            indented_script = textwrap.indent(cleaned_script, "    ")
            full_script = f"{preamble}\n\nasync def _main():\n{indented_script}\n"

            # 执行环境：预注入 _ctx（BrowserContext），preamble helper 直接引用
            exec_globals: Dict[str, Any] = {"_ctx": context}
            exec(full_script, exec_globals)
            _main_fn = exec_globals.get("_main")
            if not _main_fn:
                raise ValueError("Script compilation failed — _main not found")

            # 如果有 start_url，先打开一个初始页面
            if params.start_url:
                initial_page = await context.new_page()
                initial_page.set_default_timeout(_DEFAULT_TIMEOUT)
                await initial_page.goto(params.start_url, wait_until="domcontentloaded")
                # 同步到 exec_globals 里的 _current_page，让 helper 能感知
                exec_globals["_current_page"] = initial_page

            # 捕获 print 输出
            import io
            import contextlib
            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()

            with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                await asyncio.wait_for(
                    _main_fn(),
                    timeout=params.timeout,
                )

            raw_stdout = stdout_buf.getvalue()
            raw_stderr = stderr_buf.getvalue()

            # 从 stdout 提取 artifact 路径（helper 函数 print("[artifact] path")）
            for line in raw_stdout.splitlines():
                if line.startswith("[artifact] "):
                    artifacts.append(line[len("[artifact] "):].strip())

            # 注册 artifacts 到 FileRegistry
            registry = ctx.extra.get("file_registry") if ctx.extra else None
            if registry is not None and artifacts:
                import hashlib as _hashlib
                import mimetypes as _mimetypes
                for art_path in artifacts:
                    try:
                        p = Path(art_path)
                        if p.exists():
                            data = p.read_bytes()
                            sha256 = _hashlib.sha256(data).hexdigest()
                            mime = _mimetypes.guess_type(art_path)[0] or "application/octet-stream"
                            registry.register(
                                file_path=p,
                                sha256=sha256,
                                size=len(data),
                                mime_type=mime,
                                source_url=params.start_url or "",
                                task_id=ctx.extra.get("task_id", ""),
                                node_id=ctx.extra.get("node_id", ""),
                                skill_name="browser.run",
                            )
                    except Exception as reg_err:
                        logger.warning(f"[browser.run] FileRegistry registration failed for {art_path}: {reg_err}")

            # 截断 stdout/stderr
            truncated = len(raw_stdout) > _MAX_STDOUT or len(raw_stderr) > _MAX_STDERR
            stdout_out = raw_stdout[:_MAX_STDOUT] + ("\n...[truncated]" if len(raw_stdout) > _MAX_STDOUT else "")
            stderr_out = raw_stderr[:_MAX_STDERR] + ("\n...[truncated]" if len(raw_stderr) > _MAX_STDERR else "")

            # 取最后一个活跃页面的 URL 和 title
            pages = context.pages
            if pages:
                last_page = pages[-1]
                try:
                    final_url = last_page.url
                    page_title = await last_page.title()
                except Exception:
                    pass

            # 语义校验：脚本有抓取意图但没有任何产出
            # stdout 为空 + artifacts 为空 = 脚本执行了但什么都没抓到
            # 这是一个语义失败，返回 success=False 让 Planner 知道需要换策略
            # retryable=False：重试同一脚本不会有不同结果，让 Planner 换策略
            has_fetch_intent = (
                params.start_url is not None
                or any(kw in params.script for kw in ("open_page", "new_page", "goto"))
            )
            has_output = bool(stdout_out.strip()) or bool(artifacts)
            if has_fetch_intent and not has_output:
                if stderr_out.strip():
                    logger.warning(f"[browser.run] Script stderr:\n{stderr_out[:2000]}")
                return BrowserRunOutput(
                    success=False,
                    message=(
                        "Script executed but produced no output. "
                        "The script called open_page() but did not print() any data or save any artifacts. "
                        "Possible causes: selector not found, page content blocked, or missing print() call. "
                        "Try a different URL, a different selector, or add explicit print() statements."
                    ),
                    stdout=stdout_out,
                    stderr=stderr_out,
                    artifacts=artifacts,
                    final_url=final_url,
                    page_title=page_title,
                    truncated=truncated,
                    retryable=False,
                )

            return BrowserRunOutput(
                success=True,
                message="Browser script executed successfully",
                stdout=stdout_out,
                stderr=stderr_out,
                output=stdout_out or None,
                artifacts=artifacts,
                final_url=final_url,
                page_title=page_title,
                truncated=truncated,
            )

        except asyncio.TimeoutError:
            return BrowserRunOutput(
                success=False,
                message=f"Script timed out after {params.timeout}s",
                stderr=f"TimeoutError: exceeded {params.timeout}s",
            )
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.warning(f"[browser.run] Script error: {e}")
            return BrowserRunOutput(
                success=False,
                message=str(e),
                stderr=tb[:_MAX_STDERR],
            )
        finally:
            # 任务结束立即销毁 context（per-task 隔离）
            try:
                await context.close()
            except Exception:
                pass
