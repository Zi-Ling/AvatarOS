# app/services/computer/wait_engine.py
"""WaitEngine — 统一等待语义."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from .models import (
    ComputerUseSessionState,
    GUIState,
    WaitCondition,
    WaitResult,
)
from .ocr_service import OCRService
from .screen_analyzer import ScreenAnalyzer
from .uia_service import UIAutomationService

logger = logging.getLogger(__name__)


class WaitEngine:
    """统一等待引擎."""

    def __init__(
        self,
        screen_analyzer: ScreenAnalyzer,
        ocr_service: OCRService,
        uia_service: UIAutomationService,
        event_bus: Any = None,
    ) -> None:
        self._analyzer = screen_analyzer
        self._ocr = ocr_service
        self._uia = uia_service
        self._event_bus = event_bus

    async def wait_for_condition(
        self,
        condition: WaitCondition,
        session_state: Optional[ComputerUseSessionState] = None,
    ) -> WaitResult:
        """轮询等待条件满足."""
        start = time.monotonic()
        desc_lower = condition.description.lower()

        while True:
            elapsed = time.monotonic() - start
            if elapsed >= condition.timeout:
                return WaitResult(condition_met=False, elapsed_seconds=elapsed)

            try:
                analysis = await self._analyzer.analyze()
                gui_state = analysis.gui_state

                # Check if element appears/disappears
                found = any(
                    desc_lower in (e.name or e.text or "").lower()
                    for e in gui_state.visible_elements
                )

                if condition.appear and found:
                    return WaitResult(
                        condition_met=True,
                        elapsed_seconds=time.monotonic() - start,
                        final_state=gui_state,
                    )
                if not condition.appear and not found:
                    return WaitResult(
                        condition_met=True,
                        elapsed_seconds=time.monotonic() - start,
                        final_state=gui_state,
                    )
            except Exception as e:
                logger.warning("Wait poll error: %s", e)

            await asyncio.sleep(condition.poll_interval)

    async def wait_for_ui_stable(
        self,
        timeout: float = 30.0,
        stability_threshold: float = 1.0,
    ) -> WaitResult:
        """等待 UI 稳定（连续 stability_threshold 秒内 state_hash 不变）."""
        start = time.monotonic()
        last_hash: Optional[str] = None
        stable_since: Optional[float] = None

        while True:
            elapsed = time.monotonic() - start
            if elapsed >= timeout:
                return WaitResult(condition_met=False, elapsed_seconds=elapsed)

            try:
                analysis = await self._analyzer.analyze()
                current_hash = analysis.gui_state.state_hash

                if current_hash == last_hash:
                    if stable_since is not None:
                        stable_duration = time.monotonic() - stable_since
                        if stable_duration >= stability_threshold:
                            return WaitResult(
                                condition_met=True,
                                elapsed_seconds=time.monotonic() - start,
                                final_state=analysis.gui_state,
                            )
                else:
                    last_hash = current_hash
                    stable_since = time.monotonic()
            except Exception as e:
                logger.warning("UI stability check error: %s", e)

            await asyncio.sleep(0.3)
