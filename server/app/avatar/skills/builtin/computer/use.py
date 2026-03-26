# app/avatar/skills/builtin/computer/use.py
"""Computer Use skills — computer.use, computer.read_screen, etc."""

from __future__ import annotations

import logging
from typing import Any, Optional

from ...base import BaseSkill, SkillSpec, SideEffect, SkillRiskLevel
from ...context import SkillContext
from ...registry import register_skill
from ...schema import SkillOutput
from app.avatar.runtime.graph.models.output_contract import (
    SkillOutputContract,
    TransportMode,
    ValueKind,
)
from app.services.computer.models import (
    ClickElementInput,
    ClickElementOutput,
    ComputerUseInput,
    ComputerUseOutput,
    FillFormInput,
    FillFormOutput,
    ReadScreenInput,
    ReadScreenOutput,
    TypeTextInput,
    TypeTextOutput,
    WaitForInput,
    WaitForOutput,
)

logger = logging.getLogger(__name__)


# ── Runtime instance management ───────────────────────────────────────

_runtime_cache: dict[str, Any] = {}


def _get_computer_use_runtime(ctx: SkillContext) -> Any:
    """获取或创建 ComputerUseRuntime 实例.

    从全局 AvatarMain 实例获取 llm_client / event_bus 等运行时依赖，
    而非从 SkillContext（它是轻量级 dataclass，不携带这些重量级服务）。
    vision 相关组件使用 vision 专用 LLM client（支持多模态）。
    """
    cache_key = "default"
    if cache_key in _runtime_cache:
        return _runtime_cache[cache_key]

    from app.services.computer.runtime import ComputerUseRuntime
    from app.core.bootstrap import get_avatar_main
    from app.services.approval_service import get_approval_service
    from app.llm.factory import create_vision_llm_client

    avatar = get_avatar_main()
    vision_client = create_vision_llm_client()

    runtime = ComputerUseRuntime(
        llm_client=avatar.llm_client if avatar else None,
        event_bus=avatar.event_bus if avatar else None,
        artifact_store=getattr(avatar, '_graph_executor', None)
        and getattr(avatar._graph_executor, 'artifact_store', None),
        approval_service=get_approval_service(),
        interrupt_manager=None,
        vision_llm_client=vision_client,
    )
    _runtime_cache[cache_key] = runtime
    return runtime


# ── computer.use ──────────────────────────────────────────────────────


@register_skill
class ComputerUseSkill(BaseSkill[ComputerUseInput, ComputerUseOutput]):
    spec = SkillSpec(
        name="computer.use",
        description="自主操控桌面应用，通过 OTAV 循环完成自然语言描述的目标。",
        input_model=ComputerUseInput,
        output_model=ComputerUseOutput,
        side_effects={SideEffect.EXEC, SideEffect.GUI_CONTROL},
        risk_level=SkillRiskLevel.EXECUTE,
        aliases=["desktop_use", "gui_automation", "computer_control"],
        tags=["computer", "desktop", "gui", "操控", "桌面", "自动化"],
        requires_host_desktop=True,
        output_contract=SkillOutputContract(
            value_kind=ValueKind.JSON,
            transport_mode=TransportMode.INLINE,
        ),
    )

    async def run(self, ctx: SkillContext, params: ComputerUseInput) -> ComputerUseOutput:
        runtime = _get_computer_use_runtime(ctx)
        result = await runtime.execute(
            goal=params.goal, ctx=ctx,
            max_steps=params.max_steps, timeout=params.timeout,
        )
        return ComputerUseOutput(
            success=result.success,
            message=result.result_summary,
            data=result.to_dict(),
            result_summary=result.result_summary,
            steps_taken=result.steps_taken,
            evidence_chain=result.evidence_chain,
            failure_reason=result.failure_reason,
        )


# ── computer.read_screen ──────────────────────────────────────────────


@register_skill
class ReadScreenSkill(BaseSkill[ReadScreenInput, ReadScreenOutput]):
    spec = SkillSpec(
        name="computer.read_screen",
        description="截屏并分析当前屏幕状态，返回结构化 GUIState。",
        input_model=ReadScreenInput,
        output_model=ReadScreenOutput,
        side_effects=set(),
        risk_level=SkillRiskLevel.READ,
        aliases=["read_screen", "screenshot_analyze"],
        tags=["screen", "screenshot", "截屏", "分析"],
        requires_host_desktop=True,
    )

    async def run(self, ctx: SkillContext, params: ReadScreenInput) -> ReadScreenOutput:
        runtime = _get_computer_use_runtime(ctx)
        gui_state = await runtime.read_screen(ctx)
        if gui_state.vision_unavailable:
            return ReadScreenOutput(
                success=False,
                retryable=False,
                message=(
                    "Vision LLM unavailable — screen analysis failed. "
                    "Do NOT retry this skill. "
                    "Use keyboard.type, keyboard.hotkey, "
                    "mouse.click and other non-visual skills instead."
                ),
                gui_state=gui_state,
            )
        return ReadScreenOutput(
            success=True,
            message=f"Screen analyzed: {gui_state.app_name} - {gui_state.window_title}",
            gui_state=gui_state,
        )


# ── computer.click_element ────────────────────────────────────────────


@register_skill
class ClickElementSkill(BaseSkill[ClickElementInput, ClickElementOutput]):
    spec = SkillSpec(
        name="computer.click_element",
        description="根据描述定位并点击 UI 元素。",
        input_model=ClickElementInput,
        output_model=ClickElementOutput,
        side_effects={SideEffect.EXEC},
        risk_level=SkillRiskLevel.WRITE,
        aliases=["click_ui", "click_button"],
        tags=["click", "点击", "按钮"],
        requires_host_desktop=True,
    )

    async def run(self, ctx: SkillContext, params: ClickElementInput) -> ClickElementOutput:
        runtime = _get_computer_use_runtime(ctx)
        result = await runtime.click_element(
            ctx=ctx, description=params.description,
            click_type=params.click_type.value,
        )
        return ClickElementOutput(
            success=result.success,
            message="Clicked" if result.success else (result.error or "Click failed"),
            clicked_coords=result.target_coords,
            locator_source=result.locator_evidence.chosen_candidate.source
            if result.locator_evidence and result.locator_evidence.chosen_candidate else None,
            confidence=result.locator_evidence.fusion_confidence
            if result.locator_evidence else 0.0,
        )


# ── computer.type_text ────────────────────────────────────────────────


@register_skill
class TypeTextSkill(BaseSkill[TypeTextInput, TypeTextOutput]):
    spec = SkillSpec(
        name="computer.type_text",
        description="定位输入框并输入文本。",
        input_model=TypeTextInput,
        output_model=TypeTextOutput,
        side_effects={SideEffect.EXEC},
        risk_level=SkillRiskLevel.WRITE,
        aliases=["type_input"],
        tags=["type", "input", "输入", "文本"],
        requires_host_desktop=True,
    )

    async def run(self, ctx: SkillContext, params: TypeTextInput) -> TypeTextOutput:
        runtime = _get_computer_use_runtime(ctx)
        result = await runtime.type_text(
            ctx=ctx, target_description=params.target_description,
            text=params.text,
        )
        return TypeTextOutput(
            success=result.success,
            message="Typed" if result.success else (result.error or "Type failed"),
            typed_text=params.text if result.success else "",
            target_coords=result.target_coords,
        )


# ── computer.wait_for ─────────────────────────────────────────────────


@register_skill
class WaitForSkill(BaseSkill[WaitForInput, WaitForOutput]):
    spec = SkillSpec(
        name="computer.wait_for",
        description="等待特定 UI 元素出现或消失。",
        input_model=WaitForInput,
        output_model=WaitForOutput,
        side_effects=set(),
        risk_level=SkillRiskLevel.READ,
        aliases=["wait_element", "wait_ui"],
        tags=["wait", "等待", "元素"],
        requires_host_desktop=True,
    )

    async def run(self, ctx: SkillContext, params: WaitForInput) -> WaitForOutput:
        runtime = _get_computer_use_runtime(ctx)
        found = await runtime.wait_for(
            ctx=ctx, description=params.description,
            timeout=params.timeout, appear=params.appear,
        )
        return WaitForOutput(
            success=True,
            message="Found" if found else "Timeout",
            found=found,
        )


# ── computer.fill_form ────────────────────────────────────────────────


@register_skill
class FillFormSkill(BaseSkill[FillFormInput, FillFormOutput]):
    spec = SkillSpec(
        name="computer.fill_form",
        description="按顺序填写表单字段（逐字段定位→填写）。复杂表单请使用 computer.use。",
        input_model=FillFormInput,
        output_model=FillFormOutput,
        side_effects={SideEffect.EXEC},
        risk_level=SkillRiskLevel.WRITE,
        aliases=["fill_form", "auto_fill"],
        tags=["form", "fill", "表单", "填写"],
        requires_host_desktop=True,
    )

    async def run(self, ctx: SkillContext, params: FillFormInput) -> FillFormOutput:
        runtime = _get_computer_use_runtime(ctx)
        filled: list[str] = []
        failed: list[str] = []

        for field in params.fields:
            try:
                result = await runtime.type_text(
                    ctx=ctx,
                    target_description=field.field_description,
                    text=field.value,
                )
                if result.success:
                    filled.append(field.field_description)
                else:
                    failed.append(field.field_description)
                    break
            except Exception:
                failed.append(field.field_description)
                break

        return FillFormOutput(
            success=len(failed) == 0,
            message=f"Filled {len(filled)}/{len(params.fields)} fields",
            filled_fields=filled,
            failed_fields=failed,
        )
