# app/services/computer/screen_analyzer.py
"""ScreenAnalyzer — LLM 多模态屏幕分析 + ObservationBundle 生成."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel

from .models import (
    AnalysisResult,
    DialogInfo,
    DominantLayout,
    GUIState,
    ObservationBundle,
    VisibleElement,
)

if TYPE_CHECKING:
    from .ocr_service import OCRService
    from .uia_service import UIAutomationService

logger = logging.getLogger(__name__)


_ANALYZE_PROMPT = (
    "Analyze this screenshot and return a JSON object with these fields:\n"
    '- "app_name": current foreground application name\n'
    '- "window_title": current window title\n'
    '- "dominant_layout": one of dialog/form/list/editor/browser/unknown\n'
    '- "visible_elements": list of {name, element_type, text, bbox:[x,y,w,h], is_enabled, is_focused}\n'
    '- "active_dialog": {title, dialog_type, buttons, message} or null\n'
    '- "loading_state": boolean\n'
    '- "extracted_text": key text visible on screen\n'
    "Return ONLY valid JSON, no markdown."
)


class CacheEntry(BaseModel):
    """ScreenAnalyzer 缓存条目，含 TTL 和窗口一致性校验."""
    result: AnalysisResult
    timestamp: float
    window_title: str
    foreground_hwnd: Optional[int] = None


class ScreenAnalyzer:
    """LLM 多模态屏幕分析器."""

    def __init__(
        self,
        llm_client: Any,
        screen_driver: Any,
        cache_ttl: float = 3.0,
    ) -> None:
        self._llm = llm_client
        self._screen = screen_driver
        self._cache: dict[str, CacheEntry] = {}
        self._cache_ttl = cache_ttl

    # ── public API ────────────────────────────────────────────────────

    async def analyze(
        self,
        roi: Optional[tuple[int, int, int, int]] = None,
        context_hint: Optional[str] = None,
    ) -> AnalysisResult:
        """截屏 → hash → 缓存命中则复用 → 否则 LLM 分析."""
        screenshot_b64 = await self._take_screenshot(roi)
        image_hash = self._compute_image_hash(screenshot_b64)

        current_title, current_hwnd = await self._get_foreground_info()

        cached = self._cache.get(image_hash)
        if cached and self._is_cache_valid(cached, current_title, current_hwnd):
            return cached.result

        gui_state = await self._analyze_with_llm(screenshot_b64, context_hint)
        result = AnalysisResult(
            gui_state=gui_state,
            screenshot_b64=screenshot_b64,
            image_hash=image_hash,
        )
        self._cache[image_hash] = CacheEntry(
            result=result,
            timestamp=time.time(),
            window_title=current_title,
            foreground_hwnd=current_hwnd,
        )
        return result

    async def analyze_with_screenshot(
        self,
        screenshot_b64: str,
        context_hint: Optional[str] = None,
    ) -> AnalysisResult:
        """对已有截图进行分析（避免重复截屏）."""
        image_hash = self._compute_image_hash(screenshot_b64)
        gui_state = await self._analyze_with_llm(screenshot_b64, context_hint)
        return AnalysisResult(
            gui_state=gui_state,
            screenshot_b64=screenshot_b64,
            image_hash=image_hash,
        )

    async def create_observation_bundle(
        self,
        ocr_service: "OCRService",
        uia_service: "UIAutomationService",
        roi: Optional[tuple[int, int, int, int]] = None,
        context_hint: Optional[str] = None,
    ) -> ObservationBundle:
        """一次性产出完整 ObservationBundle."""
        analysis = await self.analyze(roi=roi, context_hint=context_hint)
        current_title, current_hwnd = await self._get_foreground_info()

        ocr_blocks = await ocr_service.extract(analysis.screenshot_b64, roi=roi)
        try:
            uia_elements = await uia_service.get_control_tree(
                window_title=current_title
            )
        except Exception:
            logger.warning("UIA control tree unavailable, degrading gracefully")
            uia_elements = []

        return ObservationBundle(
            screenshot_b64=analysis.screenshot_b64,
            image_hash=analysis.image_hash,
            gui_state=analysis.gui_state,
            ocr_blocks=ocr_blocks,
            uia_elements=uia_elements,
            foreground_window_title=current_title,
            foreground_hwnd=current_hwnd,
        )

    def invalidate_cache(self) -> None:
        self._cache.clear()

    def _is_cache_valid(
        self,
        entry: CacheEntry,
        current_window_title: str,
        current_hwnd: Optional[int],
    ) -> bool:
        if time.time() - entry.timestamp > self._cache_ttl:
            return False
        if entry.window_title != current_window_title:
            return False
        if current_hwnd is not None and entry.foreground_hwnd != current_hwnd:
            return False
        return True

    # ── private helpers ───────────────────────────────────────────────

    async def _take_screenshot(
        self, roi: Optional[tuple[int, int, int, int]] = None
    ) -> str:
        """截屏并返回 base64 编码."""
        if roi:
            return await self._screen.capture_region(*roi)
        return await self._screen.capture_full()

    async def _get_foreground_info(self) -> tuple[str, Optional[int]]:
        """获取前台窗口标题和句柄."""
        try:
            title = getattr(self._screen, "get_foreground_title", lambda: "")()
            hwnd = getattr(self._screen, "get_foreground_hwnd", lambda: None)()
            return (title or "", hwnd)
        except Exception:
            return ("", None)

    @staticmethod
    def _compute_image_hash(screenshot_b64: str) -> str:
        return hashlib.sha256(screenshot_b64.encode()).hexdigest()[:16]

    async def _analyze_with_llm(
        self,
        screenshot_b64: str,
        context_hint: Optional[str] = None,
    ) -> GUIState:
        """调用 LLM 多模态分析截图，返回 GUIState."""
        prompt = _ANALYZE_PROMPT
        if context_hint:
            prompt += f"\nContext: {context_hint}"

        try:
            response = await self._llm.chat_with_vision(
                prompt=prompt,
                image_b64=screenshot_b64,
            )
            data = self._parse_llm_response(response)
        except Exception as e:
            logger.error("LLM analysis failed: %s", e)
            data = {}

        return self._build_gui_state(data)

    @staticmethod
    def _parse_llm_response(response: Any) -> dict:
        text = getattr(response, "content", str(response))
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse LLM JSON response")
            return {}

    @staticmethod
    def _build_gui_state(data: dict) -> GUIState:
        elements = [
            VisibleElement(**e) for e in data.get("visible_elements", [])
        ]
        dialog_raw = data.get("active_dialog")
        dialog = DialogInfo(**dialog_raw) if dialog_raw else None

        app_name = data.get("app_name", "unknown")
        window_title = data.get("window_title", "unknown")
        dominant = data.get("dominant_layout", "unknown")
        extracted_text = data.get("extracted_text", "")

        try:
            layout = DominantLayout(dominant)
        except ValueError:
            layout = DominantLayout.UNKNOWN

        elements_summary = GUIState._normalize_elements_summary(elements)
        state_hash = GUIState.compute_hash(
            app_name=app_name,
            window_title=window_title,
            elements_summary=elements_summary,
            dominant_layout=layout.value,
            dialog_title=dialog.title if dialog else "",
            ocr_text_prefix=extracted_text,
        )

        return GUIState(
            app_name=app_name,
            window_title=window_title,
            dominant_layout=layout,
            visible_elements=elements,
            active_dialog=dialog,
            loading_state=data.get("loading_state", False),
            extracted_text=extracted_text,
            state_hash=state_hash,
            ui_signature=state_hash,
        )
