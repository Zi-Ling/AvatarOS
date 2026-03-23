# app/avatar/skills/builtin/computer/mouse.py

from pydantic import BaseModel, Field
from typing import Literal, Optional
from ...base import BaseSkill, SkillSpec, SkillOutput, SideEffect, SkillRiskLevel
from ...registry import register_skill
from ....actions.gui.drivers import MouseDriver

# --- Models ---
class MouseMoveInput(BaseModel):
    x: int = Field(..., description="Target X coordinate")
    y: int = Field(..., description="Target Y coordinate")
    duration: float = Field(0.5, description="Movement duration in seconds")

class MouseClickInput(BaseModel):
    button: Literal["left", "right", "middle"] = Field("left", description="Mouse button")
    clicks: int = Field(1, description="Number of clicks")
    interval: float = Field(0.1, description="Interval between clicks")

class MouseClickAtInput(MouseMoveInput, MouseClickInput):
    pass # Combines move and click

class MouseDragInput(BaseModel):
    x: int = Field(..., description="Target X coordinate")
    y: int = Field(..., description="Target Y coordinate")
    duration: float = Field(0.5, description="Drag duration")
    button: Literal["left", "right", "middle"] = Field("left", description="Mouse button holding down")

class MouseScrollInput(BaseModel):
    clicks: int = Field(..., description="Scroll amount (positive=up, negative=down)")

# --- Skills ---

@register_skill
class MouseMoveSkill(BaseSkill):
    spec = SkillSpec(
        name="computer.mouse.move",
        description="Move the mouse cursor to specific coordinates. 移动鼠标到指定坐标。",
        input_model=MouseMoveInput,
        output_model=SkillOutput,
        side_effects=set(),
        risk_level=SkillRiskLevel.READ,
        aliases=["mouse.move", "move_mouse"],
        tags=["mouse", "move", "cursor", "鼠标", "移动", "光标"],
        requires_host_desktop=True,
    )

    async def run(self, ctx: "SkillContext", input_data: MouseMoveInput) -> SkillOutput:
        driver = MouseDriver()
        driver.move_to(input_data.x, input_data.y, input_data.duration)
        return SkillOutput(success=True, message=f"Moved mouse to ({input_data.x}, {input_data.y})")

@register_skill
class MouseClickSkill(BaseSkill):
    spec = SkillSpec(
        name="computer.mouse.click",
        description="Click the mouse button at the current location. 在当前位置点击鼠标。",
        input_model=MouseClickInput,
        output_model=SkillOutput,
        side_effects=set(),
        risk_level=SkillRiskLevel.WRITE,
        aliases=["mouse.click", "click_mouse"],
        tags=["mouse", "click", "鼠标", "点击"],
        requires_host_desktop=True,
    )

    async def run(self, ctx: "SkillContext", input_data: MouseClickInput) -> SkillOutput:
        driver = MouseDriver()
        driver.click(input_data.button, input_data.clicks, input_data.interval)
        return SkillOutput(success=True, message=f"Clicked {input_data.button} button {input_data.clicks} times")

@register_skill
class MouseClickAtSkill(BaseSkill):
    spec = SkillSpec(
        name="computer.mouse.click_at",
        description="Move the mouse to coordinates and click. 移动鼠标到指定坐标并点击。",
        input_model=MouseClickAtInput,
        output_model=SkillOutput,
        side_effects=set(),
        risk_level=SkillRiskLevel.WRITE,
        aliases=["click_coords", "mouse.click_pos"],
        tags=["mouse", "click", "鼠标", "点击"],
        requires_host_desktop=True,
    )

    async def run(self, ctx: "SkillContext", input_data: MouseClickAtInput) -> SkillOutput:
        driver = MouseDriver()
        driver.click_at(input_data.x, input_data.y, input_data.button, input_data.clicks)
        return SkillOutput(success=True, message=f"Clicked at ({input_data.x}, {input_data.y})")

@register_skill
class MouseDragSkill(BaseSkill):
    spec = SkillSpec(
        name="computer.mouse.drag",
        description="Drag the mouse from current position to target coordinates. 拖拽鼠标到目标坐标。",
        input_model=MouseDragInput,
        output_model=SkillOutput,
        side_effects=set(),
        risk_level=SkillRiskLevel.WRITE,
        aliases=["mouse.drag", "drag_drop"],
        tags=["mouse", "drag", "drop", "鼠标", "拖拽", "拖动"],
        requires_host_desktop=True,
    )

    async def run(self, ctx: "SkillContext", input_data: MouseDragInput) -> SkillOutput:
        driver = MouseDriver()
        driver.drag_to(input_data.x, input_data.y, input_data.duration, input_data.button)
        return SkillOutput(success=True, message=f"Dragged mouse to ({input_data.x}, {input_data.y})")

@register_skill
class MouseScrollSkill(BaseSkill):
    spec = SkillSpec(
        name="computer.mouse.scroll",
        description="Scroll the mouse wheel up or down. 滚动鼠标滚轮。",
        input_model=MouseScrollInput,
        output_model=SkillOutput,
        side_effects=set(),
        risk_level=SkillRiskLevel.READ,
        aliases=["mouse.scroll", "scroll"],
        tags=["mouse", "scroll", "鼠标", "滚动"],
        requires_host_desktop=True,
    )

    async def run(self, ctx: "SkillContext", input_data: MouseScrollInput) -> SkillOutput:
        driver = MouseDriver()
        driver.scroll(input_data.clicks)
        return SkillOutput(success=True, message=f"Scrolled mouse {input_data.clicks} clicks")
