# app/services/computer/locator_resolver.py
"""LocatorResolver — 多源证据加权评分融合定位."""

from __future__ import annotations

import logging
import math
from difflib import SequenceMatcher
from typing import Optional

from .models import (
    GUIState,
    LocatorCandidate,
    LocatorResult,
    LocatorScoringWeights,
    LocatorSource,
)
from .ocr_service import OCRService
from .screen_analyzer import ScreenAnalyzer
from .uia_service import UIAutomationService

logger = logging.getLogger(__name__)

# Source prior scores
_SOURCE_PRIORS: dict[LocatorSource, float] = {
    LocatorSource.UIA: 0.9,
    LocatorSource.OCR: 0.6,
    LocatorSource.LLM_VISION: 0.4,
}


class LocatorResolver:
    """多源证据融合定位器 — 加权评分模型."""

    def __init__(
        self,
        uia_service: UIAutomationService,
        ocr_service: OCRService,
        screen_analyzer: ScreenAnalyzer,
        confidence_threshold: float = 0.3,
        scoring_weights: Optional[LocatorScoringWeights] = None,
    ) -> None:
        self._uia = uia_service
        self._ocr = ocr_service
        self._analyzer = screen_analyzer
        self._threshold = confidence_threshold
        self._weights = scoring_weights or LocatorScoringWeights()

    async def resolve(
        self,
        target_description: str,
        gui_state: GUIState,
        screenshot_b64: str,
        screen_size: tuple[int, int],
        window_title_hint: Optional[str] = None,
        last_click_point: Optional[tuple[int, int]] = None,
    ) -> LocatorResult:
        """多源定位融合."""
        candidates: list[LocatorCandidate] = []

        # Collect UIA candidates
        try:
            uia_candidates = await self._collect_uia(target_description, window_title_hint)
            candidates.extend(uia_candidates)
        except Exception as e:
            logger.warning("UIA collection failed: %s", e)

        # Collect OCR candidates
        try:
            ocr_candidates = await self._collect_ocr(target_description, screenshot_b64)
            candidates.extend(ocr_candidates)
        except Exception as e:
            logger.warning("OCR collection failed: %s", e)

        # Collect LLM vision candidates from gui_state visible_elements
        llm_candidates = self._collect_from_gui_state(target_description, gui_state)
        candidates.extend(llm_candidates)

        return self._fuse_candidates(
            candidates, screen_size, target_description,
            window_title_hint, last_click_point,
        )

    def _score_candidate(
        self,
        candidate: LocatorCandidate,
        target_description: str,
        window_title_hint: Optional[str],
        last_click_point: Optional[tuple[int, int]],
    ) -> float:
        """计算单个候选的加权得分."""
        w = self._weights

        # Source prior
        source_score = _SOURCE_PRIORS.get(candidate.source, 0.3)

        # Text similarity
        elem_text = ""
        if candidate.element_info:
            elem_text = candidate.element_info.get("name", "") or candidate.element_info.get("text", "")
        text_sim = SequenceMatcher(None, target_description.lower(), elem_text.lower()).ratio() if elem_text else 0.0

        # Visibility state
        vis_score = 1.0
        if candidate.element_info:
            if not candidate.element_info.get("is_enabled", True):
                vis_score = 0.2
            if not candidate.element_info.get("is_visible", True):
                vis_score = 0.1

        # Window consistency
        win_score = 1.0
        if window_title_hint and candidate.element_info:
            cand_window = candidate.element_info.get("window_title", "")
            if cand_window and window_title_hint.lower() not in cand_window.lower():
                win_score = 0.3

        # History proximity
        hist_score = 0.5  # neutral default
        if last_click_point and candidate.bbox:
            cx = candidate.bbox[0] + candidate.bbox[2] // 2
            cy = candidate.bbox[1] + candidate.bbox[3] // 2
            dist = math.sqrt((cx - last_click_point[0]) ** 2 + (cy - last_click_point[1]) ** 2)
            hist_score = max(0.0, 1.0 - dist / 2000.0)

        return (
            w.source_prior * source_score
            + w.text_similarity * text_sim
            + w.visibility_state * vis_score
            + w.window_consistency * win_score
            + w.history_proximity * hist_score
        )

    def _fuse_candidates(
        self,
        candidates: list[LocatorCandidate],
        screen_size: tuple[int, int],
        target_description: str,
        window_title_hint: Optional[str] = None,
        last_click_point: Optional[tuple[int, int]] = None,
    ) -> LocatorResult:
        """融合规则（加权评分）."""
        if not candidates:
            return LocatorResult(success=False, decision_reason="No candidates found")

        sw, sh = screen_size
        scored: list[tuple[float, LocatorCandidate]] = []

        for c in candidates:
            # Reject off-screen
            x, y, bw, bh = c.bbox
            if x + bw <= 0 or y + bh <= 0 or x >= sw or y >= sh:
                continue
            score = self._score_candidate(c, target_description, window_title_hint, last_click_point)
            scored.append((score, c))

        if not scored:
            return LocatorResult(
                success=False,
                all_candidates=candidates,
                decision_reason="All candidates off-screen or rejected",
            )

        scored.sort(key=lambda t: t[0], reverse=True)
        best_score, best = scored[0]

        if best_score < self._threshold:
            return LocatorResult(
                success=False,
                all_candidates=candidates,
                fusion_confidence=best_score,
                decision_reason=f"Best score {best_score:.3f} below threshold {self._threshold}",
            )

        # Compute click point (center of bbox)
        cx = best.bbox[0] + best.bbox[2] // 2
        cy = best.bbox[1] + best.bbox[3] // 2
        # Clamp to screen
        cx = max(0, min(cx, sw - 1))
        cy = max(0, min(cy, sh - 1))

        return LocatorResult(
            success=True,
            chosen_candidate=best,
            all_candidates=candidates,
            fusion_confidence=best_score,
            decision_reason=f"Selected {best.source.value} candidate (score={best_score:.3f})",
            click_point=(cx, cy),
        )

    # ── candidate collection helpers ──────────────────────────────────

    async def _collect_uia(
        self, target_description: str, window_title_hint: Optional[str]
    ) -> list[LocatorCandidate]:
        elem = await self._uia.find_element(
            name=target_description, window_title=window_title_hint
        )
        if not elem or not elem.bounding_rect:
            return []
        return [
            LocatorCandidate(
                source=LocatorSource.UIA,
                bbox=elem.bounding_rect,
                confidence=0.9 if elem.is_enabled and elem.is_visible else 0.5,
                reason=f"UIA match: {elem.name} ({elem.control_type})",
                element_info={
                    "name": elem.name,
                    "control_type": elem.control_type,
                    "is_enabled": elem.is_enabled,
                    "is_visible": elem.is_visible,
                    "automation_id": elem.automation_id,
                },
            )
        ]

    async def _collect_ocr(
        self, target_description: str, screenshot_b64: str
    ) -> list[LocatorCandidate]:
        blocks = await self._ocr.extract(screenshot_b64)
        candidates: list[LocatorCandidate] = []
        target_lower = target_description.lower()
        for block in blocks:
            if not block.text:
                continue
            sim = SequenceMatcher(None, target_lower, block.text.lower()).ratio()
            if sim < 0.3:
                continue
            candidates.append(
                LocatorCandidate(
                    source=LocatorSource.OCR,
                    bbox=block.bbox,
                    confidence=min(0.8, sim),
                    reason=f"OCR text match: '{block.text}' (sim={sim:.2f})",
                    element_info={"text": block.text},
                )
            )
        return candidates

    @staticmethod
    def _collect_from_gui_state(
        target_description: str, gui_state: GUIState
    ) -> list[LocatorCandidate]:
        candidates: list[LocatorCandidate] = []
        target_lower = target_description.lower()
        for elem in gui_state.visible_elements:
            if not elem.bbox:
                continue
            text = elem.name or elem.text or ""
            if not text:
                continue
            sim = SequenceMatcher(None, target_lower, text.lower()).ratio()
            if sim < 0.2:
                continue
            candidates.append(
                LocatorCandidate(
                    source=LocatorSource.LLM_VISION,
                    bbox=elem.bbox,
                    confidence=min(0.6, sim * 0.8),
                    reason=f"LLM vision element: '{text}' (sim={sim:.2f})",
                    element_info={
                        "name": elem.name,
                        "text": elem.text,
                        "element_type": elem.element_type,
                        "is_enabled": elem.is_enabled,
                    },
                )
            )
        return candidates
