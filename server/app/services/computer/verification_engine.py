# app/services/computer/verification_engine.py
"""VerificationEngine — 8 种验证策略引擎."""

from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine, Optional

from .models import (
    ElementAppearedParams,
    ElementDisappearedParams,
    GUIState,
    ScreenshotDiffParams,
    StateHashChangedParams,
    TextChangedParams,
    TextContainsParams,
    UIAPropertyChangedParams,
    VerificationParams,
    VerificationResult,
    VerificationStrategy,
    VerificationVerdict,
    WindowTitleChangedParams,
)
from .ocr_service import OCRService
from .screen_analyzer import ScreenAnalyzer
from .uia_service import UIAutomationService

logger = logging.getLogger(__name__)


class VerificationEngine:
    """8 种验证策略引擎."""

    def __init__(
        self,
        screen_analyzer: ScreenAnalyzer,
        ocr_service: OCRService,
        uia_service: UIAutomationService,
    ) -> None:
        self._analyzer = screen_analyzer
        self._ocr = ocr_service
        self._uia = uia_service
        self._strategies: dict[str, Callable[..., Coroutine[Any, Any, VerificationResult]]] = {
            VerificationStrategy.ELEMENT_APPEARED.value: self._verify_element_appeared,
            VerificationStrategy.ELEMENT_DISAPPEARED.value: self._verify_element_disappeared,
            VerificationStrategy.TEXT_CHANGED.value: self._verify_text_changed,
            VerificationStrategy.TEXT_CONTAINS.value: self._verify_text_contains,
            VerificationStrategy.WINDOW_TITLE_CHANGED.value: self._verify_window_title_changed,
            VerificationStrategy.SCREENSHOT_DIFF.value: self._verify_screenshot_diff,
            VerificationStrategy.STATE_HASH_CHANGED.value: self._verify_state_hash_changed,
            VerificationStrategy.UIA_PROPERTY_CHANGED.value: self._verify_uia_property_changed,
        }

    async def verify(
        self,
        strategy: str,
        params: VerificationParams,
        before_state: GUIState,
        after_state: GUIState,
        before_screenshot_b64: str,
        after_screenshot_b64: str,
    ) -> VerificationResult:
        handler = self._strategies.get(strategy)
        if not handler:
            try:
                strat_enum = VerificationStrategy(strategy)
            except ValueError:
                strat_enum = VerificationStrategy.STATE_HASH_CHANGED
            return VerificationResult(
                verdict=VerificationVerdict.INCONCLUSIVE,
                strategy=strat_enum,
                details=f"Unknown strategy: {strategy}",
            )
        try:
            return await handler(
                params, before_state, after_state,
                before_screenshot_b64, after_screenshot_b64,
            )
        except Exception as e:
            logger.error("Verification error (%s): %s", strategy, e)
            return VerificationResult(
                verdict=VerificationVerdict.INCONCLUSIVE,
                strategy=VerificationStrategy(strategy),
                details=f"Error: {e}",
            )

    # ── strategy implementations ──────────────────────────────────────

    async def _verify_element_appeared(
        self, params: VerificationParams, before: GUIState, after: GUIState,
        before_ss: str, after_ss: str,
    ) -> VerificationResult:
        assert isinstance(params, ElementAppearedParams)
        desc = params.element_description.lower()
        for elem in after.visible_elements:
            name = (elem.name or elem.text or "").lower()
            if desc in name or name in desc:
                if params.element_type and elem.element_type != params.element_type:
                    continue
                return VerificationResult(
                    verdict=VerificationVerdict.PASS,
                    strategy=VerificationStrategy.ELEMENT_APPEARED,
                    evidence={"matched_element": elem.name},
                    details=f"Element '{params.element_description}' found",
                )
        return VerificationResult(
            verdict=VerificationVerdict.FAIL,
            strategy=VerificationStrategy.ELEMENT_APPEARED,
            details=f"Element '{params.element_description}' not found in after state",
        )

    async def _verify_element_disappeared(
        self, params: VerificationParams, before: GUIState, after: GUIState,
        before_ss: str, after_ss: str,
    ) -> VerificationResult:
        assert isinstance(params, ElementDisappearedParams)
        desc = params.element_description.lower()
        # Check it existed before
        found_before = any(
            desc in (e.name or e.text or "").lower() for e in before.visible_elements
        )
        found_after = any(
            desc in (e.name or e.text or "").lower() for e in after.visible_elements
        )
        if found_before and not found_after:
            return VerificationResult(
                verdict=VerificationVerdict.PASS,
                strategy=VerificationStrategy.ELEMENT_DISAPPEARED,
                details=f"Element '{params.element_description}' disappeared",
            )
        if not found_before:
            return VerificationResult(
                verdict=VerificationVerdict.INCONCLUSIVE,
                strategy=VerificationStrategy.ELEMENT_DISAPPEARED,
                details="Element was not found in before state either",
            )
        return VerificationResult(
            verdict=VerificationVerdict.FAIL,
            strategy=VerificationStrategy.ELEMENT_DISAPPEARED,
            details=f"Element '{params.element_description}' still present",
        )

    async def _verify_text_changed(
        self, params: VerificationParams, before: GUIState, after: GUIState,
        before_ss: str, after_ss: str,
    ) -> VerificationResult:
        assert isinstance(params, TextChangedParams)
        before_text = await self._ocr.extract_text_only(before_ss)
        after_text = await self._ocr.extract_text_only(after_ss)
        if before_text != after_text:
            return VerificationResult(
                verdict=VerificationVerdict.PASS,
                strategy=VerificationStrategy.TEXT_CHANGED,
                evidence={"before_text_len": len(before_text), "after_text_len": len(after_text)},
                details="Text content changed",
            )
        return VerificationResult(
            verdict=VerificationVerdict.FAIL,
            strategy=VerificationStrategy.TEXT_CHANGED,
            details="Text content unchanged",
        )

    async def _verify_text_contains(
        self, params: VerificationParams, before: GUIState, after: GUIState,
        before_ss: str, after_ss: str,
    ) -> VerificationResult:
        assert isinstance(params, TextContainsParams)
        after_text = await self._ocr.extract_text_only(after_ss)
        if params.expected_text.lower() in after_text.lower():
            return VerificationResult(
                verdict=VerificationVerdict.PASS,
                strategy=VerificationStrategy.TEXT_CONTAINS,
                details=f"Text contains '{params.expected_text}'",
            )
        return VerificationResult(
            verdict=VerificationVerdict.FAIL,
            strategy=VerificationStrategy.TEXT_CONTAINS,
            details=f"Text does not contain '{params.expected_text}'",
        )

    async def _verify_window_title_changed(
        self, params: VerificationParams, before: GUIState, after: GUIState,
        before_ss: str, after_ss: str,
    ) -> VerificationResult:
        assert isinstance(params, WindowTitleChangedParams)
        if params.expected_title_contains.lower() in after.window_title.lower():
            return VerificationResult(
                verdict=VerificationVerdict.PASS,
                strategy=VerificationStrategy.WINDOW_TITLE_CHANGED,
                evidence={"new_title": after.window_title},
                details=f"Window title contains '{params.expected_title_contains}'",
            )
        return VerificationResult(
            verdict=VerificationVerdict.FAIL,
            strategy=VerificationStrategy.WINDOW_TITLE_CHANGED,
            details=f"Window title '{after.window_title}' does not contain '{params.expected_title_contains}'",
        )

    async def _verify_screenshot_diff(
        self, params: VerificationParams, before: GUIState, after: GUIState,
        before_ss: str, after_ss: str,
    ) -> VerificationResult:
        assert isinstance(params, ScreenshotDiffParams)
        # Simple hash-based diff (pixel-level would require image decoding)
        if before_ss == after_ss:
            diff_ratio = 0.0
        else:
            # Estimate diff by comparing base64 strings character by character
            min_len = min(len(before_ss), len(after_ss))
            if min_len == 0:
                diff_ratio = 1.0
            else:
                diffs = sum(1 for a, b in zip(before_ss[:min_len], after_ss[:min_len]) if a != b)
                diff_ratio = diffs / min_len

        if diff_ratio >= params.diff_threshold:
            return VerificationResult(
                verdict=VerificationVerdict.PASS,
                strategy=VerificationStrategy.SCREENSHOT_DIFF,
                evidence={"diff_ratio": diff_ratio},
                details=f"Screenshot diff {diff_ratio:.3f} >= threshold {params.diff_threshold}",
            )
        return VerificationResult(
            verdict=VerificationVerdict.FAIL,
            strategy=VerificationStrategy.SCREENSHOT_DIFF,
            evidence={"diff_ratio": diff_ratio},
            details=f"Screenshot diff {diff_ratio:.3f} < threshold {params.diff_threshold}",
        )

    async def _verify_state_hash_changed(
        self, params: VerificationParams, before: GUIState, after: GUIState,
        before_ss: str, after_ss: str,
    ) -> VerificationResult:
        assert isinstance(params, StateHashChangedParams)
        if before.state_hash != after.state_hash:
            return VerificationResult(
                verdict=VerificationVerdict.PASS,
                strategy=VerificationStrategy.STATE_HASH_CHANGED,
                evidence={"before_hash": before.state_hash, "after_hash": after.state_hash},
                details="State hash changed",
            )
        return VerificationResult(
            verdict=VerificationVerdict.FAIL,
            strategy=VerificationStrategy.STATE_HASH_CHANGED,
            details="State hash unchanged",
        )

    async def _verify_uia_property_changed(
        self, params: VerificationParams, before: GUIState, after: GUIState,
        before_ss: str, after_ss: str,
    ) -> VerificationResult:
        assert isinstance(params, UIAPropertyChangedParams)
        try:
            elem = await self._uia.find_element(name=params.element_name)
            if not elem:
                return VerificationResult(
                    verdict=VerificationVerdict.INCONCLUSIVE,
                    strategy=VerificationStrategy.UIA_PROPERTY_CHANGED,
                    details=f"Element '{params.element_name}' not found via UIA",
                )
            current_value = getattr(elem, params.property_name, None)
            if current_value is None:
                current_value = elem.value

            if params.expected_value is not None:
                if str(current_value) == params.expected_value:
                    return VerificationResult(
                        verdict=VerificationVerdict.PASS,
                        strategy=VerificationStrategy.UIA_PROPERTY_CHANGED,
                        evidence={"current_value": str(current_value)},
                        details=f"Property matches expected value",
                    )
                return VerificationResult(
                    verdict=VerificationVerdict.FAIL,
                    strategy=VerificationStrategy.UIA_PROPERTY_CHANGED,
                    details=f"Property value '{current_value}' != expected '{params.expected_value}'",
                )
            # No expected value — just check it changed (inconclusive without before value)
            return VerificationResult(
                verdict=VerificationVerdict.INCONCLUSIVE,
                strategy=VerificationStrategy.UIA_PROPERTY_CHANGED,
                details="No expected_value provided for comparison",
            )
        except Exception as e:
            return VerificationResult(
                verdict=VerificationVerdict.INCONCLUSIVE,
                strategy=VerificationStrategy.UIA_PROPERTY_CHANGED,
                details=f"UIA error: {e}",
            )
