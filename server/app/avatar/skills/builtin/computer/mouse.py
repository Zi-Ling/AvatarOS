# app/avatar/skills/builtin/computer/mouse.py

from pydantic import BaseModel, Field
from typing import Literal, Optional
from ...base import BaseSkill, SkillSpec, SkillOutput, SkillCategory, SkillMetadata, SkillDomain, SkillCapability
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
        api_name="computer.mouse.move",
        internal_name="computer.mouse.move_v1",
        aliases=["mouse.move", "move_mouse"],
        description="Move the mouse cursor to specific coordinates. 移动鼠标到指定坐标。",
        category=SkillCategory.COMPUTER,
        input_model=MouseMoveInput,
        output_model=SkillOutput,
        
        # Capability Routing
        meta=SkillMetadata(
            domain=SkillDomain.UI,
            capabilities={SkillCapability.NAVIGATE},
            risk_level="low"
        ),
        
        synonyms=[
            "move cursor",
            "point mouse",
            "hover over",
            "移动鼠标",
            "移动光标"
        ],
        tags=["computer", "mouse", "move", "鼠标", "移动"]
    )

    async def run(self, ctx: "SkillContext", input_data: MouseMoveInput) -> SkillOutput:
        driver = MouseDriver()
        driver.move_to(input_data.x, input_data.y, input_data.duration)
        return SkillOutput(success=True, message=f"Moved mouse to ({input_data.x}, {input_data.y})")

@register_skill
class MouseClickSkill(BaseSkill):
    spec = SkillSpec(
        name="computer.mouse.click",
        api_name="computer.mouse.click",
        internal_name="computer.mouse.click_v1",
        aliases=["mouse.click", "click_mouse"],
        description="Click the mouse button at the current location. 在当前位置点击鼠标。",
        category=SkillCategory.COMPUTER,
        input_model=MouseClickInput,
        output_model=SkillOutput,
        
        # Capability Routing
        meta=SkillMetadata(
            domain=SkillDomain.UI,
            capabilities={SkillCapability.EXECUTE}, # Clicks are execution triggers
            risk_level="normal"
        ),
        
        synonyms=[
            "left click",
            "right click",
            "double click",
            "press mouse button",
            "点击鼠标",
            "鼠标点击",
            "双击"
        ],
        tags=["computer", "mouse", "click", "鼠标", "点击"]
    )

    async def run(self, ctx: "SkillContext", input_data: MouseClickInput) -> SkillOutput:
        driver = MouseDriver()
        driver.click(input_data.button, input_data.clicks, input_data.interval)
        return SkillOutput(success=True, message=f"Clicked {input_data.button} button {input_data.clicks} times")

@register_skill
class MouseClickAtSkill(BaseSkill):
    spec = SkillSpec(
        name="computer.mouse.click_at",
        api_name="computer.mouse.click_at",
        internal_name="computer.mouse.click_at_v1",
        aliases=["click_coords", "mouse.click_pos"],
        description="Move the mouse to coordinates and click. 移动鼠标到指定坐标并点击。",
        category=SkillCategory.COMPUTER,
        input_model=MouseClickAtInput,
        output_model=SkillOutput,
        
        # Capability Routing
        meta=SkillMetadata(
            domain=SkillDomain.UI,
            capabilities={SkillCapability.EXECUTE, SkillCapability.NAVIGATE},
            risk_level="normal"
        ),
        
        synonyms=[
            "click at position",
            "tap on screen",
            "click coordinates",
            "move and click",
            "点击坐标",
            "移动并点击"
        ],
        tags=["computer", "mouse", "click", "鼠标", "点击", "移动"]
    )

    async def run(self, ctx: "SkillContext", input_data: MouseClickAtInput) -> SkillOutput:
        driver = MouseDriver()
        driver.click_at(input_data.x, input_data.y, input_data.button, input_data.clicks)
        return SkillOutput(success=True, message=f"Clicked at ({input_data.x}, {input_data.y})")

@register_skill
class MouseDragSkill(BaseSkill):
    spec = SkillSpec(
        name="computer.mouse.drag",
        api_name="computer.mouse.drag",
        internal_name="computer.mouse.drag_v1",
        aliases=["mouse.drag", "drag_drop"],
        description="Drag the mouse from current position to target coordinates. 拖拽鼠标到目标坐标。",
        category=SkillCategory.COMPUTER,
        input_model=MouseDragInput,
        output_model=SkillOutput,
        
        # Capability Routing
        meta=SkillMetadata(
            domain=SkillDomain.UI,
            capabilities={SkillCapability.MODIFY, SkillCapability.NAVIGATE}, # Dragging often modifies UI state
            risk_level="normal"
        ),
        
        synonyms=[
            "drag and drop",
            "hold and move",
            "slide mouse",
            "拖拽鼠标",
            "拖动"
        ],
        tags=["computer", "mouse", "drag", "鼠标", "拖拽"]
    )

    async def run(self, ctx: "SkillContext", input_data: MouseDragInput) -> SkillOutput:
        driver = MouseDriver()
        driver.drag_to(input_data.x, input_data.y, input_data.duration, input_data.button)
        return SkillOutput(success=True, message=f"Dragged mouse to ({input_data.x}, {input_data.y})")

@register_skill
class MouseScrollSkill(BaseSkill):
    spec = SkillSpec(
        name="computer.mouse.scroll",
        api_name="computer.mouse.scroll",
        internal_name="computer.mouse.scroll_v1",
        aliases=["mouse.scroll", "scroll"],
        description="Scroll the mouse wheel up or down. 滚动鼠标滚轮。",
        category=SkillCategory.COMPUTER,
        input_model=MouseScrollInput,
        output_model=SkillOutput,
        synonyms=[
            "scroll page",
            "wheel up",
            "wheel down",
            "scroll down",
            "滚动鼠标",
            "滚轮滚动",
            "向下滚动"
        ],
        tags=["computer", "mouse", "scroll", "鼠标", "滚动", "滚轮"]
    )

    async def run(self, ctx: "SkillContext", input_data: MouseScrollInput) -> SkillOutput:
        driver = MouseDriver()
        driver.scroll(input_data.clicks)
        return SkillOutput(success=True, message=f"Scrolled mouse {input_data.clicks} clicks")
