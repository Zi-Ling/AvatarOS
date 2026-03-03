# app/avatar/skills/builtin/web.py

from __future__ import annotations

from typing import Optional, Any
from pydantic import Field

from ..base import BaseSkill, SkillSpec, SkillCategory, SkillPermission, SkillMetadata, SkillDomain, SkillCapability
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext

# Import the Singleton Driver
from ...actions.web.playwright_driver import global_playwright_driver

# ============================================================================
# web.open_page
# ============================================================================

class WebOpenPageInput(SkillInput):
    url: str = Field(..., description="The target webpage URL to open.")

class WebOpenPageOutput(SkillOutput):
    url: str
    current_url: Optional[str] = None

@register_skill
class WebOpenPageSkill(BaseSkill[WebOpenPageInput, WebOpenPageOutput]):
    spec = SkillSpec(
        name="web.open_page",
        api_name="browser.open",
        aliases=["web.open", "web.visit", "url.open"],
        description="Open a webpage URL using Playwright browser. 使用浏览器打开网页。",
        category=SkillCategory.WEB,
        input_model=WebOpenPageInput,
        output_model=WebOpenPageOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.WEB,
            capabilities={SkillCapability.NAVIGATE},
            risk_level="normal"
        ),
        
        synonyms=[
            "open website",
            "visit url",
            "go to site",
            "navigate to page",
            "打开网页",
            "访问网站",
            "浏览网页"
        ],
        examples=[
            {"description": "Open webpage", "params": {"url": "https://example.com"}}
        ],
        permissions=[
            SkillPermission(name="web_access", description="Access external websites")
        ],
        tags=["web", "browser", "网页", "浏览器", "访问"]
    )

    async def run(self, ctx: SkillContext, params: WebOpenPageInput) -> WebOpenPageOutput:
        if ctx.dry_run:
            return WebOpenPageOutput(
                success=True, 
                message=f"[dry_run] Would open: {params.url}", 
                url=params.url
            )

        try:
            # Execute
            page = await global_playwright_driver.get_page()
            await page.goto(params.url, wait_until="domcontentloaded", timeout=30000)
            
            # Post-execution verification
            current_url = page.url
            
            # Verify page loaded successfully
            if not current_url:
                return WebOpenPageOutput(success=False, message=f"Verification Failed: Page URL is empty", url=params.url)
            
            # Verify we're on the expected domain (handle redirects)
            from urllib.parse import urlparse
            expected_domain = urlparse(params.url).netloc
            actual_domain = urlparse(current_url).netloc
            
            # Allow redirects within same domain or to www/non-www variants
            if expected_domain and actual_domain:
                expected_clean = expected_domain.replace('www.', '')
                actual_clean = actual_domain.replace('www.', '')
                if expected_clean != actual_clean:
                    # Different domain - might be redirect, log but don't fail
                    pass
            
            # Verify page is not an error page (basic check)
            title = await page.title()
            if not title or title.lower() in ['404', 'error', 'not found']:
                return WebOpenPageOutput(success=False, message=f"Verification Failed: Page appears to be an error page (title: {title})", url=params.url, current_url=current_url)
            
            # Auto-save cookies after successful navigation
            await global_playwright_driver.save_cookies_after_navigation()
            
            return WebOpenPageOutput(
                success=True,
                message=f"Opened webpage: {params.url} (title: {title})",
                url=params.url,
                current_url=current_url
            )
        except TimeoutError:
            return WebOpenPageOutput(success=False, message=f"Timeout: Page took too long to load", url=params.url)
        except Exception as e:
            return WebOpenPageOutput(success=False, message=f"Failed to open page: {str(e)}", url=params.url)


# ============================================================================
# web.click
# ============================================================================

class WebClickInput(SkillInput):
    selector: Optional[str] = Field(None, description="CSS selector of the element to click.")
    text: Optional[str] = Field(None, description="Visible text of the element to click.")
    timeout: int = Field(8000, description="Maximum waiting time (ms).")

class WebClickOutput(SkillOutput):
    selector: Optional[str] = None
    text: Optional[str] = None

@register_skill
class WebClickSkill(BaseSkill[WebClickInput, WebClickOutput]):
    spec = SkillSpec(
        name="web.click",
        api_name="browser.click",
        aliases=["page.click", "click_element"],
        description="Click an element by CSS selector or visible text. 点击网页元素。",
        category=SkillCategory.WEB,
        input_model=WebClickInput,
        output_model=WebClickOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.WEB,
            capabilities={SkillCapability.NAVIGATE},
            risk_level="normal"
        ),
        
        synonyms=[
            "click button",
            "tap link",
            "点击按钮",
            "点击元素",
            "press element",
            "select option"
        ],
        examples=[
            {"description": "Click element by selector", "params": {"selector": "#submit-button"}},
            {"description": "Click element by text", "params": {"text": "Submit"}}
        ],
        tags=["web", "interaction", "网页", "点击", "浏览器"]
    )

    async def run(self, ctx: SkillContext, params: WebClickInput) -> WebClickOutput:
        if not params.selector and not params.text:
             return WebClickOutput(success=False, message="Either 'selector' or 'text' must be provided.")

        if ctx.dry_run:
             return WebClickOutput(success=True, message="[dry_run] Clicked.", selector=params.selector, text=params.text)

        try:
            page = await global_playwright_driver.get_page()
            
            # Pre-execution: Record current URL for verification
            url_before = page.url
            
            # Execute
            if params.selector:
                await page.wait_for_selector(params.selector, timeout=params.timeout)
                await page.click(params.selector)
            elif params.text:
                await page.get_by_text(params.text, exact=False).click()
            
            # Post-execution verification: Wait for potential navigation/state change
            await page.wait_for_timeout(500)  # Small delay for UI updates
            url_after = page.url
            
            # Verify click had some effect (URL changed OR page state changed)
            # Note: Not all clicks cause navigation, so we can't strictly require URL change
            verification_msg = "Clicked."
            if url_before != url_after:
                verification_msg = f"Clicked and navigated from {url_before} to {url_after}"
                # Auto-save cookies after navigation (login, form submit, etc.)
                await global_playwright_driver.save_cookies_after_navigation()
            
            return WebClickOutput(success=True, message=verification_msg, selector=params.selector, text=params.text)
        except TimeoutError:
            return WebClickOutput(success=False, message=f"Timeout: Element not found within {params.timeout}ms", selector=params.selector, text=params.text)
        except Exception as e:
            return WebClickOutput(success=False, message=f"Click failed: {str(e)}", selector=params.selector, text=params.text)


# ============================================================================
# web.fill
# ============================================================================

class WebFillInput(SkillInput):
    selector: str = Field(..., description="CSS selector of the input.")
    text: Optional[str] = Field(None, description="Text value to input.")
    # Robustness: Alias for 'text' as models often use 'value'
    value: Optional[str] = Field(None, description="Alias for text.")

class WebFillOutput(SkillOutput):
    selector: str
    input_text: str

@register_skill
class WebFillSkill(BaseSkill[WebFillInput, WebFillOutput]):
    spec = SkillSpec(
        name="web.fill",
        api_name="browser.fill",
        aliases=["page.fill", "fill_form", "browser_type"],
        description="Fill a form input by CSS selector. 填写表单输入框。",
        category=SkillCategory.WEB,
        input_model=WebFillInput,
        output_model=WebFillOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.WEB,
            capabilities={SkillCapability.WRITE},
            risk_level="normal"
        ),
        
        synonyms=[
            "type into input",
            "enter text",
            "填写表单",
            "输入内容",
            "fill form",
            "input value"
        ],
        examples=[
            {"description": "Fill form input", "params": {"selector": "#username", "text": "user@example.com"}}
        ],
        tags=["web", "form", "网页", "表单", "填写", "输入"]
    )

    async def run(self, ctx: SkillContext, params: WebFillInput) -> WebFillOutput:
        # Resolve input text from aliases
        input_text = params.text or params.value
        if not input_text:
             return WebFillOutput(
                success=False, 
                message="Missing input text. Provide 'text' or 'value'.", 
                selector=params.selector, 
                input_text=""
            )

        if ctx.dry_run:
            return WebFillOutput(
                success=True, 
                message=f"[dry_run] Fill {params.selector}", 
                selector=params.selector, 
                input_text=input_text
            )

        try:
            page = await global_playwright_driver.get_page()
            
            # Pre-execution: Wait for element
            await page.wait_for_selector(params.selector, timeout=8000)
            
            # Execute
            await page.fill(params.selector, input_text)
            
            # Post-execution verification: Read back the value
            actual_value = await page.input_value(params.selector)
            
            if actual_value != input_text:
                return WebFillOutput(
                    success=False,
                    message=f"Verification Failed: Expected '{input_text}' but got '{actual_value}'",
                    selector=params.selector,
                    input_text=input_text
                )
            
            return WebFillOutput(
                success=True,
                message=f"Filled '{params.selector}' with '{input_text}' (verified)",
                selector=params.selector,
                input_text=input_text
            )
        except TimeoutError:
            return WebFillOutput(success=False, message=f"Timeout: Element '{params.selector}' not found", selector=params.selector, input_text=input_text)
        except Exception as e:
            return WebFillOutput(success=False, message=f"Fill failed: {str(e)}", selector=params.selector, input_text=input_text)


# ============================================================================
# web.read_text
# ============================================================================

class WebReadTextInput(SkillInput):
    selector: str = Field(..., description="CSS selector of the element.")

class WebReadTextOutput(SkillOutput):
    selector: str
    text: Optional[str] = None

@register_skill
class WebReadTextSkill(BaseSkill[WebReadTextInput, WebReadTextOutput]):
    spec = SkillSpec(
        name="web.read_text",
        api_name="browser.read_text",
        aliases=["page.read", "scrape"],
        description="Read the inner text of an element. 读取网页元素文本内容。",
        category=SkillCategory.WEB,
        input_model=WebReadTextInput,
        output_model=WebReadTextOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.WEB,
            capabilities={SkillCapability.READ},
            risk_level="normal"
        ),
        
        synonyms=[
            "scrape text",
            "get content",
            "读取网页内容",
            "获取文本",
            "网页爬虫",
            "read website",
            "extract text"
        ],
        examples=[
            {"description": "Read element text", "params": {"selector": "#content"}}
        ],
        tags=["web", "scraping", "网页", "爬虫", "读取", "内容"]
    )

    async def run(self, ctx: SkillContext, params: WebReadTextInput) -> WebReadTextOutput:
        if ctx.dry_run:
            return WebReadTextOutput(
                success=True, 
                message="[dry_run] Read text", 
                selector=params.selector
            )

        try:
            page = await global_playwright_driver.get_page()
            await page.wait_for_selector(params.selector)
            value = await page.inner_text(params.selector)
            return WebReadTextOutput(
                success=True,
                message="Read text success",
                selector=params.selector,
                text=value
            )
        except Exception as e:
            return WebReadTextOutput(success=False, message=str(e), selector=params.selector)


# ============================================================================
# browser.select — 下拉框选择
# ============================================================================

class WebSelectInput(SkillInput):
    selector: str = Field(..., description="CSS selector of the <select> element.")
    value: Optional[str] = Field(None, description="Option value attribute to select.")
    label: Optional[str] = Field(None, description="Visible text of the option to select.")
    index: Optional[int] = Field(None, description="Zero-based index of the option to select.")
    timeout: int = Field(10000, description="Timeout in ms.")

class WebSelectOutput(SkillOutput):
    selector: str = ""
    selected_value: Optional[str] = None
    selected_label: Optional[str] = None


@register_skill
class WebSelectSkill(BaseSkill[WebSelectInput, WebSelectOutput]):
    spec = SkillSpec(
        name="web.select",
        api_name="browser.select",
        aliases=["page.select", "dropdown.select"],
        description="Select an option from a <select> dropdown. 从下拉框中选择选项。",
        category=SkillCategory.WEB,
        input_model=WebSelectInput,
        output_model=WebSelectOutput,
        meta=SkillMetadata(
            domain=SkillDomain.WEB,
            capabilities={SkillCapability.MODIFY},
            risk_level="normal",
        ),
        synonyms=[
            "select dropdown",
            "choose option",
            "pick from list",
            "选择下拉框",
            "下拉选择",
            "选择选项",
        ],
        examples=[
            {"description": "Select by value", "params": {"selector": "#country", "value": "CN"}},
            {"description": "Select by label", "params": {"selector": "#country", "label": "China"}},
        ],
        tags=["web", "interaction", "dropdown", "select", "下拉框", "选择"],
    )

    async def run(self, ctx: SkillContext, params: WebSelectInput) -> WebSelectOutput:
        if not params.value and not params.label and params.index is None:
            return WebSelectOutput(
                success=False,
                message="At least one of 'value', 'label', or 'index' must be provided.",
                selector=params.selector,
            )

        if ctx.dry_run:
            return WebSelectOutput(success=True, message="[dry_run] Selected.", selector=params.selector)

        try:
            page = await global_playwright_driver.get_page()
            await page.wait_for_selector(params.selector, timeout=params.timeout)

            # Playwright select_option accepts value, label, or index
            option_spec: dict[str, Any] = {}
            if params.value is not None:
                option_spec["value"] = params.value
            elif params.label is not None:
                option_spec["label"] = params.label
            elif params.index is not None:
                option_spec["index"] = params.index

            selected = await page.select_option(params.selector, **option_spec)

            # Read back what was selected
            sel_value = selected[0] if selected else None
            sel_label = None
            if sel_value:
                try:
                    sel_label = await page.eval_on_selector(
                        f'{params.selector} option[value="{sel_value}"]',
                        "el => el.textContent",
                    )
                except Exception:
                    pass

            return WebSelectOutput(
                success=True,
                message=f"Selected option: {sel_label or sel_value}",
                selector=params.selector,
                selected_value=sel_value,
                selected_label=sel_label,
            )
        except TimeoutError:
            return WebSelectOutput(
                success=False,
                message=f"Timeout: <select> element not found within {params.timeout}ms",
                selector=params.selector,
            )
        except Exception as e:
            return WebSelectOutput(
                success=False,
                message=f"Select failed: {e}",
                selector=params.selector,
            )


# ============================================================================
# browser.download — 文件下载
# ============================================================================

class WebDownloadInput(SkillInput):
    selector: Optional[str] = Field(None, description="CSS selector of the download link/button to click.")
    url: Optional[str] = Field(None, description="Direct download URL (if no click needed).")
    save_as: Optional[str] = Field(None, description="Target filename (relative to workspace). Auto-generated if omitted.")
    timeout: int = Field(30000, description="Download timeout in ms.")

class WebDownloadOutput(SkillOutput):
    path: Optional[str] = None
    filename: Optional[str] = None
    size_bytes: int = 0


@register_skill
class WebDownloadSkill(BaseSkill[WebDownloadInput, WebDownloadOutput]):
    spec = SkillSpec(
        name="web.download",
        api_name="browser.download",
        aliases=["page.download", "download_file"],
        description="Download a file by clicking a link/button or from a direct URL. 下载文件。",
        category=SkillCategory.WEB,
        input_model=WebDownloadInput,
        output_model=WebDownloadOutput,
        meta=SkillMetadata(
            domain=SkillDomain.WEB,
            capabilities={SkillCapability.READ, SkillCapability.WRITE},
            risk_level="normal",
        ),
        produces_artifact=True,
        artifact_type="file:download",
        artifact_path_field="path",
        synonyms=[
            "download file",
            "save file from web",
            "下载文件",
            "保存网页文件",
            "导出文件",
            "export report",
            "导出报表",
        ],
        examples=[
            {"description": "Download by clicking", "params": {"selector": "#export-btn"}},
            {"description": "Download from URL", "params": {"url": "https://example.com/report.xlsx"}},
        ],
        tags=["web", "download", "file", "下载", "导出", "报表"],
    )

    async def run(self, ctx: SkillContext, params: WebDownloadInput) -> WebDownloadOutput:
        import os

        if not params.selector and not params.url:
            return WebDownloadOutput(
                success=False,
                message="Either 'selector' (click to download) or 'url' (direct download) must be provided.",
            )

        if ctx.dry_run:
            return WebDownloadOutput(success=True, message="[dry_run] Would download file.")

        try:
            page = await global_playwright_driver.get_page()

            if params.selector:
                # Click-triggered download
                async with page.expect_download(timeout=params.timeout) as dl_info:
                    await page.click(params.selector)
                download = await dl_info.value
            elif params.url:
                # Direct URL download
                async with page.expect_download(timeout=params.timeout) as dl_info:
                    await page.evaluate(f'() => {{ const a = document.createElement("a"); a.href = "{params.url}"; a.download = ""; document.body.appendChild(a); a.click(); a.remove(); }}')
                download = await dl_info.value
            else:
                return WebDownloadOutput(success=False, message="No download source specified.")

            # Determine save path
            suggested = download.suggested_filename or "download"
            if params.save_as:
                save_path = ctx.resolve_path(params.save_as)
            else:
                save_path = ctx.resolve_path(suggested)

            # Ensure parent dir exists
            os.makedirs(save_path.parent, exist_ok=True)
            await download.save_as(str(save_path))

            size = os.path.getsize(str(save_path))

            # 保存 cookies（下载后可能有新的 session state）
            await global_playwright_driver.save_cookies()

            return WebDownloadOutput(
                success=True,
                message=f"Downloaded: {save_path.name} ({size} bytes)",
                path=str(save_path),
                filename=save_path.name,
                size_bytes=size,
            )
        except TimeoutError:
            return WebDownloadOutput(
                success=False,
                message=f"Download timed out after {params.timeout}ms",
            )
        except Exception as e:
            return WebDownloadOutput(
                success=False,
                message=f"Download failed: {e}",
            )
