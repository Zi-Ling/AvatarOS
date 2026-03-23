# app/services/computer/runtime.py
"""ComputerUseRuntime — 顶层编排器 + create_runtime_components 工厂."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from .action_executor import ActionExecutor
from .goal_judge import GoalJudge
from .locator_resolver import LocatorResolver
from .models import (
    ActionPlan,
    ActionResult,
    ActionTarget,
    ActionType,
    ClickType,
    ComputerUseConfig,
    ComputerUseResult,
    ComputerUseSessionState,
    FormFieldAction,
    GUIState,
    LocatorResult,
    WaitCondition,
)
from .ocr_service import OCRService
from .otav_loop import OTAVLoopController
from .safety_guard import SafetyGuard
from .screen_analyzer import ScreenAnalyzer
from .state_judge import StateTransitionJudge
from .stuck_detector import StuckDetector
from .uia_service import UIAutomationService
from .verification_engine import VerificationEngine
from .wait_engine import WaitEngine

logger = logging.getLogger(__name__)


def create_runtime_components(
    llm_client: Any,
    approval_service: Any,
    config: ComputerUseConfig,
) -> dict[str, Any]:
    """工厂函数：按正确的依赖顺序构建所有运行时组件."""
    # Lazy import drivers to avoid import errors on non-Windows
    try:
        from app.avatar.actions.gui.drivers import (
            ScreenDriver,
            MouseDriver,
            KeyboardDriver,
        )
        from app.avatar.actions.gui.controller import DesktopController
        screen_driver = ScreenDriver()
        mouse_driver = MouseDriver()
        keyboard_driver = KeyboardDriver()
        desktop_controller = DesktopController()
    except ImportError:
        # Stub drivers for testing / non-Windows
        screen_driver = None
        mouse_driver = None
        keyboard_driver = None
        desktop_controller = None

    screen_analyzer = ScreenAnalyzer(
        llm_client, screen_driver, cache_ttl=config.cache_ttl,
    )
    ocr_service = OCRService(llm_client)
    uia_service = UIAutomationService()

    safety_guard = SafetyGuard(
        approval_service,
        max_steps=config.max_steps,
        max_duration_seconds=config.max_duration_seconds,
    )

    locator_resolver = LocatorResolver(
        uia_service, ocr_service, screen_analyzer,
        confidence_threshold=config.confidence_threshold,
    )
    action_executor = ActionExecutor(
        mouse_driver, keyboard_driver, desktop_controller,
        safety_guard=safety_guard,
        uia_service=uia_service,
        min_action_interval=config.min_action_interval,
    )
    verification_engine = VerificationEngine(screen_analyzer, ocr_service, uia_service)
    state_judge = StateTransitionJudge()
    stuck_detector = StuckDetector(
        max_unchanged_streak=config.max_unchanged_streak,
        max_failed_streak=config.max_failed_streak,
        max_unexpected_streak=config.max_unexpected_streak,
    )

    return {
        "screen_driver": screen_driver,
        "mouse_driver": mouse_driver,
        "keyboard_driver": keyboard_driver,
        "desktop_controller": desktop_controller,
        "screen_analyzer": screen_analyzer,
        "ocr_service": ocr_service,
        "uia_service": uia_service,
        "safety_guard": safety_guard,
        "locator_resolver": locator_resolver,
        "action_executor": action_executor,
        "verification_engine": verification_engine,
        "state_judge": state_judge,
        "stuck_detector": stuck_detector,
    }


class ComputerUseRuntime:
    """Computer Use 子执行器 — 顶层编排."""

    def __init__(
        self,
        llm_client: Any,
        event_bus: Any,
        artifact_store: Any,
        approval_service: Any,
        interrupt_manager: Any,
        config: Optional[ComputerUseConfig] = None,
        vision_llm_client: Any = None,
    ) -> None:
        self._config = config or ComputerUseConfig()

        # vision 专用 client：用于 ScreenAnalyzer / OCRService / GoalJudge
        _vision = vision_llm_client or llm_client

        components = create_runtime_components(
            _vision, approval_service, self._config,
        )

        self._screen_analyzer: ScreenAnalyzer = components["screen_analyzer"]
        self._ocr_service: OCRService = components["ocr_service"]
        self._uia_service: UIAutomationService = components["uia_service"]
        self._locator: LocatorResolver = components["locator_resolver"]
        self._executor: ActionExecutor = components["action_executor"]
        self._verifier: VerificationEngine = components["verification_engine"]
        self._judge: StateTransitionJudge = components["state_judge"]
        self._stuck: StuckDetector = components["stuck_detector"]
        self._safety: SafetyGuard = components["safety_guard"]

        self._goal_judge = GoalJudge(_vision)
        self._wait_engine = WaitEngine(
            screen_analyzer=self._screen_analyzer,
            ocr_service=self._ocr_service,
            uia_service=self._uia_service,
        )

        self._otav = OTAVLoopController(
            screen_analyzer=self._screen_analyzer,
            ocr_service=self._ocr_service,
            uia_service=self._uia_service,
            locator_resolver=self._locator,
            action_executor=self._executor,
            verification_engine=self._verifier,
            state_judge=self._judge,
            stuck_detector=self._stuck,
            safety_guard=self._safety,
            goal_judge=self._goal_judge,
            wait_engine=self._wait_engine,
            event_bus=event_bus,
            artifact_store=artifact_store,
            interrupt_manager=interrupt_manager,
            llm_client=llm_client,
            max_steps=self._config.max_steps,
            observe_freshness_seconds=self._config.observe_freshness_seconds,
            max_retry_per_step=self._config.max_retry_per_step,
            max_total_llm_calls=self._config.max_total_llm_calls,
            progress_report_interval=self._config.progress_report_interval,
        )

        self._event_bus = event_bus
        self._interrupt = interrupt_manager
        self._llm = llm_client

    async def execute(
        self,
        goal: str,
        ctx: Any = None,
        max_steps: Optional[int] = None,
        timeout: Optional[int] = None,
    ) -> ComputerUseResult:
        """执行 Computer Use 任务."""
        session = ComputerUseSessionState(
            session_id=str(uuid.uuid4()),
            goal=goal,
            max_steps=max_steps or self._config.max_steps,
            timeout_seconds=timeout or self._config.max_duration_seconds,
        )

        result = await self._otav.run(goal, session, ctx)

        return ComputerUseResult(
            success=result.success,
            result_summary=result.result_summary,
            steps_taken=result.steps_taken,
            evidence_chain=result.evidence_chain,
            failure_reason=result.failure_reason,
            session_id=session.session_id,
        )

    async def read_screen(self, ctx: Any = None) -> GUIState:
        """截屏 + 分析，返回 GUIState."""
        analysis = await self._screen_analyzer.analyze()
        return analysis.gui_state

    async def click_element(
        self,
        ctx: Any = None,
        description: str = "",
        click_type: str = "single",
    ) -> ActionResult:
        """定位并点击元素."""
        gui_state = await self.read_screen(ctx)
        try:
            import pyautogui  # type: ignore[import-untyped]
            screen_size = pyautogui.size()
        except Exception:
            screen_size = (1920, 1080)

        locator_result = await self._locator.resolve(
            target_description=description,
            gui_state=gui_state,
            screenshot_b64="",
            screen_size=screen_size,
        )

        plan = ActionPlan(
            action=ActionType.CLICK,
            target=ActionTarget(description=description),
        )
        plan.params.click_type = ClickType(click_type)

        session = ComputerUseSessionState(
            session_id=str(uuid.uuid4()), goal=f"Click {description}",
        )
        return await self._executor.execute(plan, locator_result, session, gui_state)

    async def type_text(
        self,
        ctx: Any = None,
        target_description: str = "",
        text: str = "",
    ) -> ActionResult:
        """定位输入框并输入文本."""
        gui_state = await self.read_screen(ctx)
        try:
            import pyautogui  # type: ignore[import-untyped]
            screen_size = pyautogui.size()
        except Exception:
            screen_size = (1920, 1080)

        locator_result = await self._locator.resolve(
            target_description=target_description,
            gui_state=gui_state,
            screenshot_b64="",
            screen_size=screen_size,
        )

        from .models import ActionParams
        plan = ActionPlan(
            action=ActionType.TYPE_TEXT,
            target=ActionTarget(description=target_description),
            params=ActionParams(text=text),
        )

        session = ComputerUseSessionState(
            session_id=str(uuid.uuid4()), goal=f"Type '{text}' into {target_description}",
        )
        return await self._executor.execute(plan, locator_result, session, gui_state)

    async def wait_for(
        self,
        ctx: Any = None,
        description: str = "",
        timeout: int = 10,
        appear: bool = True,
    ) -> bool:
        """等待元素出现或消失."""
        condition = WaitCondition(
            description=description, appear=appear, timeout=float(timeout),
        )
        result = await self._wait_engine.wait_for_condition(condition)
        return result.condition_met

    async def fill_form(
        self,
        ctx: Any = None,
        fields: Optional[list[FormFieldAction]] = None,
    ) -> ActionResult:
        """按顺序填写表单字段."""
        fields = fields or []
        filled: list[str] = []
        failed: list[str] = []

        for field in fields:
            try:
                result = await self.type_text(
                    ctx=ctx,
                    target_description=field.field_description,
                    text=field.value,
                )
                if result.success:
                    filled.append(field.field_description)
                else:
                    failed.append(field.field_description)
                    # Return partial result on first failure
                    return ActionResult(
                        success=False,
                        action_type=ActionType.TYPE_TEXT,
                        error=f"Failed to fill field: {field.field_description}",
                    )
            except Exception as e:
                failed.append(field.field_description)
                return ActionResult(
                    success=False,
                    action_type=ActionType.TYPE_TEXT,
                    error=str(e),
                )

        return ActionResult(
            success=True,
            action_type=ActionType.TYPE_TEXT,
        )
