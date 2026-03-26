# app/services/computer/otav_loop.py
"""OTAVLoopController — OTAV 循环主控制器."""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .action_executor import ActionExecutor
from .goal_judge import GoalJudge
from .locator_resolver import LocatorResolver
from .models import (
    ActionHistoryEntry,
    ActionPlan,
    ActionResult,
    ActionType,
    ComputerUseSessionState,
    EvidenceEntry,
    FallbackStrategy,
    GUIState,
    LocatorResult,
    OTAVResult,
    ProgressReport,
    StateHashChangedParams,
    TransitionType,
    TransitionVerdict,
    VerificationStrategy,
)
from .ocr_service import OCRService
from .safety_guard import SafetyGuard
from .screen_analyzer import ScreenAnalyzer
from .state_judge import StateTransitionJudge
from .stuck_detector import StuckDetector
from .uia_service import UIAutomationService
from .verification_engine import VerificationEngine
from .wait_engine import WaitEngine

logger = logging.getLogger(__name__)


_THINK_PROMPT = (
    "You are controlling a Windows desktop application.\n"
    "Goal: {goal}\n\n"
    "Current screen state:\n"
    "- App: {app_name}\n"
    "- Window: {window_title}\n"
    "- Layout: {layout}\n"
    "- Elements: {elements}\n"
    "- Key text: {extracted_text}\n\n"
    "Action history (last {history_count} steps):\n{history}\n\n"
    "{stuck_hint}"
    "Decide the next action. Return a JSON object:\n"
    '{{"action": "click|type_text|hotkey|scroll|wait|read_screen", '
    '"target": {{"description": "...", "window_title_hint": "..."}}, '
    '"params": {{...}}, '
    '"verification": {{"strategy": "...", "params": {{...}}}}, '
    '"fallback": {{"on_fail": "retry|retry_relocate|undo_and_retry|skip|abort"}}, '
    '"decision_summary": "...", '
    '"evidence_basis": ["..."]}}\n'
    "Return ONLY valid JSON."
)


class OTAVLoopController:
    """OTAV 循环主控制器."""

    def __init__(
        self,
        screen_analyzer: ScreenAnalyzer,
        ocr_service: OCRService,
        uia_service: UIAutomationService,
        locator_resolver: LocatorResolver,
        action_executor: ActionExecutor,
        verification_engine: VerificationEngine,
        state_judge: StateTransitionJudge,
        stuck_detector: StuckDetector,
        safety_guard: SafetyGuard,
        goal_judge: GoalJudge,
        wait_engine: WaitEngine,
        event_bus: Any,
        artifact_store: Any,
        interrupt_manager: Any,
        llm_client: Any,
        max_steps: int = 50,
        observe_freshness_seconds: float = 5.0,
        post_action_wait: float = 1.0,
        max_wait_timeout: float = 30.0,
        max_retry_per_step: int = 3,
        max_total_llm_calls: int = 100,
        progress_report_interval: int = 3,
    ) -> None:
        self._analyzer = screen_analyzer
        self._ocr = ocr_service
        self._uia = uia_service
        self._locator = locator_resolver
        self._executor = action_executor
        self._verifier = verification_engine
        self._judge = state_judge
        self._stuck = stuck_detector
        self._safety = safety_guard
        self._goal_judge = goal_judge
        self._wait = wait_engine
        self._event_bus = event_bus
        self._artifact = artifact_store
        self._interrupt = interrupt_manager
        self._llm = llm_client
        self._max_steps = max_steps
        self._freshness = observe_freshness_seconds
        self._post_wait = post_action_wait
        self._max_wait = max_wait_timeout
        self._max_retry = max_retry_per_step
        self._max_llm_calls = max_total_llm_calls
        self._progress_interval = progress_report_interval

    async def run(
        self,
        goal: str,
        session_state: ComputerUseSessionState,
        ctx: Any = None,
    ) -> OTAVResult:
        """执行 OTAV 循环直到目标达成或终止."""
        start_time = time.monotonic()
        evidence_chain: list[EvidenceEntry] = []
        last_gui_state: Optional[GUIState] = None
        last_screenshot: str = ""

        while session_state.current_step_index < self._max_steps:
            step = session_state.current_step_index

            # Check interrupt / user takeover
            if await self._check_user_takeover(session_state):
                await self._emit("computer.interrupted", session_state, {"interrupt_source": "user"})
                return self._build_result(
                    False, "User interrupted", session_state, evidence_chain, start_time,
                    failure_reason="user_interrupted",
                )

            # Check LLM budget
            if session_state.llm_call_count >= self._max_llm_calls:
                await self._emit("computer.finished", session_state, {"success": False})
                return self._build_result(
                    False, "LLM budget exhausted", session_state, evidence_chain, start_time,
                    failure_reason="llm_budget_exhausted",
                )

            # 1. OBSERVE
            await self._emit("computer.observe.started", session_state)
            gui_state, screenshot = await self._observe(session_state)
            last_gui_state = gui_state
            last_screenshot = screenshot

            # Vision LLM unavailable — fail fast instead of looping with empty data
            if gui_state.vision_unavailable:
                await self._emit("computer.finished", session_state, {
                    "success": False, "reason": "vision_llm_unavailable",
                })
                return self._build_result(
                    False,
                    "Vision LLM unavailable — cannot analyze screen for autonomous GUI control. "
                    "Consider using browser.run or keyboard/mouse skills instead.",
                    session_state, evidence_chain, start_time,
                    failure_reason="vision_llm_unavailable",
                )

            await self._emit("computer.observe.completed", session_state, {
                "screenshot_artifact_id": session_state.last_screenshot_artifact_id,
                "app_name": gui_state.app_name,
                "window_title": gui_state.window_title,
            })

            # Window focus check
            if session_state.active_window and gui_state.window_title != session_state.active_window:
                session_state.focus_lost_count += 1
                session_state.last_foreground_window = gui_state.window_title
                # Re-observe after focus change
                gui_state, screenshot = await self._observe(session_state)
                last_gui_state = gui_state
                last_screenshot = screenshot

            session_state.active_window = gui_state.window_title

            # 2. THINK
            action_plan = await self._think(
                goal, gui_state, session_state.action_history,
                stuck_reason=session_state.stuck_reason,
            )
            session_state.llm_call_count += 1
            await self._emit("computer.think.completed", session_state, {
                "action_type": action_plan.action.value,
                "target_description": action_plan.target.description,
                "decision_summary": action_plan.decision_summary,
            })

            # 3. Freshness check
            if session_state.last_observe_timestamp:
                age = time.time() - session_state.last_observe_timestamp
                if age > self._freshness:
                    gui_state, screenshot = await self._observe(session_state)
                    last_gui_state = gui_state
                    last_screenshot = screenshot

            # 4. Safety check
            safety = await self._safety.check_action(action_plan, session_state, gui_state)
            if not safety.allowed:
                if safety.requires_approval:
                    session_state.approval_pending = True
                    session_state.pending_action_plan = action_plan
                    session_state.pending_approval_request_id = safety.approval_request_id
                    await self._emit("computer.approval.requested", session_state, {
                        "operation_level": safety.operation_level.value,
                        "approval_request_id": safety.approval_request_id,
                    })
                    return self._build_result(
                        False, "Awaiting approval", session_state, evidence_chain, start_time,
                        failure_reason="approval_required",
                    )
                # Blocked entirely
                session_state.current_step_index += 1
                continue

            # 5. ACT
            before_state = gui_state
            before_screenshot = screenshot
            await self._emit("computer.act.started", session_state, {
                "action_type": action_plan.action.value,
            })
            action_result = await self._act(action_plan, gui_state, session_state)
            await self._emit("computer.act.completed", session_state, {
                "action_type": action_plan.action.value,
                "success": action_result.success,
                "duration_ms": action_result.duration_ms,
            })

            if not action_result.success:
                # Handle fallback
                fallback_action = await self._handle_fallback(action_plan, action_result, session_state)
                if fallback_action == "abort":
                    return self._build_result(
                        False, f"Action failed: {action_result.error}", session_state,
                        evidence_chain, start_time, failure_reason="action_failed",
                    )
                if fallback_action == "skip":
                    session_state.current_step_index += 1
                    continue
                # "continue" means retry — loop will re-observe

            # 6. Wait for UI response
            await self._wait_for_ui_response(gui_state, session_state)

            # 7. VERIFY
            after_state, verdict = await self._verify(
                action_plan, before_state, before_screenshot, session_state,
            )
            last_gui_state = after_state
            await self._emit("computer.verify.completed", session_state, {
                "strategy": action_plan.verification.strategy.value if action_plan.verification else "none",
                "verdict": verdict.verdict_type.value,
            })

            # Record evidence
            evidence_chain.append(EvidenceEntry(
                step_index=step,
                screenshot_artifact_id=session_state.last_screenshot_artifact_id,
                action_type=action_plan.action,
                target_description=action_plan.target.description,
                locator_source=action_result.locator_evidence.chosen_candidate.source
                if action_result.locator_evidence and action_result.locator_evidence.chosen_candidate else None,
                locator_confidence=action_result.locator_evidence.fusion_confidence
                if action_result.locator_evidence else 0.0,
                verification_verdict=None,
                transition_type=verdict.verdict_type,
            ))

            # Record action history
            session_state.action_history.append(ActionHistoryEntry(
                step_index=step,
                action_type=action_plan.action,
                target_description=action_plan.target.description,
                success=action_result.success,
                verdict_type=verdict.verdict_type,
                timestamp=datetime.now(timezone.utc).timestamp(),
            ))

            # 8. StuckDetector
            self._stuck.record_verdict(session_state, verdict)
            stuck_result = self._stuck.check(session_state)
            if stuck_result.is_stuck:
                await self._emit("computer.stuck.detected", session_state, {
                    "stuck_type": stuck_result.stuck_type.value if stuck_result.stuck_type else "",
                    "recommendation": stuck_result.recommendation,
                })
                if stuck_result.recommendation == "replan":
                    session_state.replan_count += 1
                    session_state.stuck_reason = f"Stuck: {stuck_result.stuck_type.value if stuck_result.stuck_type else 'unknown'}"
                    self._stuck.reset_streak(session_state)
                else:
                    return self._build_result(
                        False, "Stuck after replan", session_state, evidence_chain, start_time,
                        failure_reason="stuck_after_replan",
                    )

            # 9. GoalJudge
            goal_result = await self._goal_judge.evaluate(
                goal, after_state, session_state.action_history, last_screenshot,
            )
            session_state.llm_call_count += 1

            if goal_result.goal_achieved:
                await self._emit("computer.finished", session_state, {"success": True})
                return self._build_result(
                    True, goal_result.reason, session_state, evidence_chain, start_time,
                )

            # 10. Progress report
            if step > 0 and step % self._progress_interval == 0:
                elapsed = time.monotonic() - start_time
                report = ProgressReport(
                    session_id=session_state.session_id,
                    current_step=step,
                    max_steps=self._max_steps,
                    last_action_summary=action_plan.decision_summary,
                    estimated_progress_pct=step / self._max_steps,
                    llm_calls_used=session_state.llm_call_count,
                    llm_calls_budget=self._max_llm_calls,
                    elapsed_seconds=elapsed,
                )
                await self._emit("computer.progress", session_state, report.model_dump())

            session_state.current_step_index += 1
            session_state.stuck_reason = None

        # Max steps reached
        await self._emit("computer.finished", session_state, {"success": False})
        return self._build_result(
            False, "Max steps reached", session_state, evidence_chain, start_time,
            failure_reason="max_steps_reached",
        )

    # ── phase implementations ─────────────────────────────────────────

    async def _observe(
        self, session_state: ComputerUseSessionState
    ) -> tuple[GUIState, str]:
        """Observe 阶段."""
        bundle = await self._analyzer.create_observation_bundle(
            self._ocr, self._uia,
        )
        session_state.last_state_hash = bundle.gui_state.state_hash
        session_state.last_analysis = bundle.gui_state
        session_state.last_observe_timestamp = time.time()
        session_state.last_foreground_window = bundle.foreground_window_title

        # Register screenshot artifact
        try:
            artifact_id = await self._artifact.store(
                data=bundle.screenshot_b64,
                content_type="image/png",
                metadata={"step": session_state.current_step_index},
            )
            session_state.last_screenshot_artifact_id = artifact_id
        except Exception:
            session_state.last_screenshot_artifact_id = bundle.image_hash

        session_state.llm_call_count += 1
        return bundle.gui_state, bundle.screenshot_b64

    async def _think(
        self,
        goal: str,
        gui_state: GUIState,
        action_history: list[ActionHistoryEntry],
        stuck_reason: Optional[str] = None,
    ) -> ActionPlan:
        """Think 阶段."""
        history_lines = []
        for entry in action_history[-5:]:
            status = "✓" if entry.success else "✗"
            history_lines.append(
                f"  [{status}] {entry.action_type.value} → {entry.target_description}"
            )

        elements_desc = ", ".join(
            f"{e.name}({e.element_type})" for e in gui_state.visible_elements[:15]
        )

        stuck_hint = ""
        if stuck_reason:
            stuck_hint = (
                f"IMPORTANT: Previous approach failed ({stuck_reason}). "
                "Try a completely different strategy.\n\n"
            )

        prompt = _THINK_PROMPT.format(
            goal=goal,
            app_name=gui_state.app_name,
            window_title=gui_state.window_title,
            layout=gui_state.dominant_layout.value,
            elements=elements_desc or "(none detected)",
            extracted_text=gui_state.extracted_text[:300],
            history_count=len(history_lines),
            history="\n".join(history_lines) or "  (none)",
            stuck_hint=stuck_hint,
        )

        response = await self._llm.chat_with_vision(
            prompt=prompt,
            image_b64="",  # Text-only think step
        )
        text = getattr(response, "content", str(response)).strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            # Fallback: read_screen action
            from .models import ActionTarget as _AT
            return ActionPlan(
                action=ActionType.READ_SCREEN,
                target=_AT(description="Re-analyze screen"),
                decision_summary="Failed to parse LLM response, re-observing",
            )

        from .models import (
            ActionFallback,
            ActionParams,
            ActionTarget,
            ActionVerification,
            ClickType,
            ScrollDirection,
            VerificationStrategy,
        )

        target = ActionTarget(
            description=data.get("target", {}).get("description", "unknown"),
            window_title_hint=data.get("target", {}).get("window_title_hint"),
        )

        params_raw = data.get("params", {})
        params = ActionParams(
            text=params_raw.get("text"),
            keys=params_raw.get("keys"),
            click_type=ClickType(params_raw["click_type"]) if "click_type" in params_raw else ClickType.SINGLE,
        )
        if "direction" in params_raw:
            try:
                params.direction = ScrollDirection(params_raw["direction"])
            except ValueError:
                pass

        verification = None
        ver_raw = data.get("verification")
        if ver_raw and "strategy" in ver_raw:
            try:
                strategy = VerificationStrategy(ver_raw["strategy"])
                ver_params = self._build_verification_params(strategy, ver_raw.get("params", {}))
                if ver_params:
                    verification = ActionVerification(strategy=strategy, params=ver_params)
            except (ValueError, KeyError):
                pass

        fallback_raw = data.get("fallback", {})
        try:
            fallback = ActionFallback(on_fail=FallbackStrategy(fallback_raw.get("on_fail", "retry")))
        except ValueError:
            fallback = ActionFallback()

        return ActionPlan(
            action=ActionType(data.get("action", "read_screen")),
            target=target,
            params=params,
            verification=verification,
            fallback=fallback,
            decision_summary=data.get("decision_summary", ""),
            evidence_basis=data.get("evidence_basis", []),
        )

    async def _act(
        self,
        action_plan: ActionPlan,
        gui_state: GUIState,
        session_state: ComputerUseSessionState,
    ) -> ActionResult:
        """Act 阶段."""
        # Get screen size
        try:
            import pyautogui  # type: ignore[import-untyped]
            screen_size = pyautogui.size()
        except Exception:
            screen_size = (1920, 1080)

        locator_result = await self._locator.resolve(
            target_description=action_plan.target.description,
            gui_state=gui_state,
            screenshot_b64="",
            screen_size=screen_size,
            window_title_hint=action_plan.target.window_title_hint,
            last_click_point=session_state.action_history[-1].target_description
            if False else None,  # Simplified
        )
        session_state.last_locator_result = locator_result

        return await self._executor.execute(
            action_plan, locator_result, session_state, gui_state,
        )

    async def _verify(
        self,
        action_plan: ActionPlan,
        before_state: GUIState,
        before_screenshot: str,
        session_state: ComputerUseSessionState,
    ) -> tuple[GUIState, TransitionVerdict]:
        """Verify 阶段."""
        # Re-observe
        after_state, after_screenshot = await self._observe(session_state)

        # Determine verification strategy
        if action_plan.verification:
            strategy = action_plan.verification.strategy.value
            params = action_plan.verification.params
        else:
            strategy = VerificationStrategy.STATE_HASH_CHANGED.value
            params = StateHashChangedParams()

        ver_result = await self._verifier.verify(
            strategy, params, before_state, after_state,
            before_screenshot, after_screenshot,
        )
        session_state.last_verification_result = ver_result

        verdict = self._judge.judge(
            before_state, after_state,
            expected_transition=action_plan.decision_summary,
            verification_result=ver_result,
        )
        return after_state, verdict

    async def _wait_for_ui_response(
        self,
        gui_state: GUIState,
        session_state: ComputerUseSessionState,
    ) -> None:
        """委托 WaitEngine 等待界面响应稳定."""
        if gui_state.loading_state:
            await self._wait.wait_for_ui_stable(
                timeout=self._max_wait,
                stability_threshold=self._post_wait,
            )
        else:
            import asyncio
            await asyncio.sleep(self._post_wait)

    async def _check_user_takeover(
        self, session_state: ComputerUseSessionState
    ) -> bool:
        """检测用户是否手动接管."""
        if self._interrupt is None:
            return False
        try:
            is_interrupted = getattr(self._interrupt, "is_interrupted", lambda: False)
            if callable(is_interrupted):
                return is_interrupted()
            return bool(is_interrupted)
        except Exception:
            return False

    async def _handle_fallback(
        self,
        action_plan: ActionPlan,
        action_result: ActionResult,
        session_state: ComputerUseSessionState,
    ) -> str:
        """根据 fallback 策略处理失败. Returns: continue/skip/abort."""
        strategy = action_plan.fallback.on_fail

        if strategy == FallbackStrategy.ABORT:
            return "abort"

        if strategy == FallbackStrategy.SKIP:
            return "skip"

        if session_state.retry_count >= self._max_retry:
            session_state.retry_count = 0
            return "skip"

        session_state.retry_count += 1

        if strategy == FallbackStrategy.UNDO_AND_RETRY:
            try:
                await self._executor._execute_hotkey(["ctrl", "z"])
            except Exception:
                pass

        await self._emit("computer.retry.scheduled", session_state, {
            "retry_count": session_state.retry_count,
            "fallback_strategy": strategy.value,
            "reason": action_result.error or "action failed",
        })

        return "continue"

    # ── helpers ────────────────────────────────────────────────────────

    async def _emit(
        self,
        event_type: str,
        session_state: ComputerUseSessionState,
        extra: Optional[dict] = None,
    ) -> None:
        if not self._event_bus:
            return
        payload = {
            "session_id": session_state.session_id,
            "step_index": session_state.current_step_index,
            "state_hash": session_state.last_state_hash,
            "timestamp": time.time(),
            "attempt_index": session_state.retry_count,
            "replan_count": session_state.replan_count,
            "action_id": None,
        }
        if extra:
            payload.update(extra)
        try:
            from app.avatar.runtime.events.types import Event, EventType as ET
            # EventBus.publish 接受 Event 对象，同步方法
            event = Event(
                type=ET.NODE_STARTED,  # 通用事件类型，payload 中携带具体 event_type
                source="otav_loop",
                payload={"otav_event": event_type, **payload},
            )
            self._event_bus.publish(event)
        except Exception as e:
            logger.warning("Event emit failed: %s", e)

    def _build_result(
        self,
        success: bool,
        summary: str,
        session_state: ComputerUseSessionState,
        evidence_chain: list[EvidenceEntry],
        start_time: float,
        failure_reason: Optional[str] = None,
    ) -> OTAVResult:
        return OTAVResult(
            success=success,
            result_summary=summary,
            steps_taken=session_state.current_step_index,
            evidence_chain=evidence_chain,
            failure_reason=failure_reason,
            final_gui_state=session_state.last_analysis,
            total_duration_ms=(time.monotonic() - start_time) * 1000,
            llm_calls=session_state.llm_call_count,
        )

    @staticmethod
    def _build_verification_params(strategy: VerificationStrategy, raw: dict) -> Any:
        from .models import (
            ElementAppearedParams,
            ElementDisappearedParams,
            ScreenshotDiffParams,
            StateHashChangedParams,
            TextChangedParams,
            TextContainsParams,
            UIAPropertyChangedParams,
            WindowTitleChangedParams,
        )
        mapping = {
            VerificationStrategy.ELEMENT_APPEARED: ElementAppearedParams,
            VerificationStrategy.ELEMENT_DISAPPEARED: ElementDisappearedParams,
            VerificationStrategy.TEXT_CHANGED: TextChangedParams,
            VerificationStrategy.TEXT_CONTAINS: TextContainsParams,
            VerificationStrategy.WINDOW_TITLE_CHANGED: WindowTitleChangedParams,
            VerificationStrategy.SCREENSHOT_DIFF: ScreenshotDiffParams,
            VerificationStrategy.STATE_HASH_CHANGED: StateHashChangedParams,
            VerificationStrategy.UIA_PROPERTY_CHANGED: UIAPropertyChangedParams,
        }
        cls = mapping.get(strategy)
        if cls:
            try:
                return cls(**raw)
            except Exception:
                return cls() if strategy == VerificationStrategy.STATE_HASH_CHANGED else None
        return None
