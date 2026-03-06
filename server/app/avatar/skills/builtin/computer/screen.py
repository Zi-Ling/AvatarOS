from pydantic import BaseModel, Field, field_validator
from typing import Optional, Tuple, Any, Union, List
import json
from ...base import BaseSkill, SkillSpec, SkillOutput, SideEffect, SkillRiskLevel
from ...registry import register_skill
from ....actions.gui.drivers import ScreenDriver

# --- Models ---
class ScreenCaptureInput(BaseModel):
    region: Optional[Union[Tuple[int, int, int, int], List[int], str]] = Field(None, description="Region to capture (left, top, width, height). Defaults to full screen if None or empty.")

    @field_validator('region', mode='before')
    @classmethod
    def parse_region(cls, v):
        if v is None or v == "" or v == "full":
            return None
        if isinstance(v, str):
            try:
                # Handle "[0,0,100,100]" or "0,0,100,100"
                v = v.strip("[]()")
                parts = [int(x.strip()) for x in v.split(",")]
                return tuple(parts)
            except Exception:
                # If parsing fails, default to None (full screen) to be safe
                return None
        if isinstance(v, list):
            return tuple(v)
        return v


class ScreenInfoInput(BaseModel):
    pass # No input required

class ScreenCaptureOutput(SkillOutput):
    base64_image: str = Field(..., description="Base64 encoded PNG image of the screen")

class ScreenInfoOutput(SkillOutput):
    info: dict = Field(..., description="Screen resolution and cursor position")

# --- Skills ---

@register_skill
class ScreenCaptureSkill(BaseSkill):
    spec = SkillSpec(
        name="computer.screen.capture",
        description="Capture a screenshot of the entire screen or a specific region. 截取屏幕截图。",
        input_model=ScreenCaptureInput,
        output_model=ScreenCaptureOutput,
        side_effects=set(),
        risk_level=SkillRiskLevel.READ,
        aliases=["screen.capture", "screenshot", "take_screenshot"],
    )

    async def run(self, ctx: "SkillContext", input_data: ScreenCaptureInput) -> ScreenCaptureOutput:
        driver = ScreenDriver()
        b64_img = driver.capture_base64(input_data.region)
        return ScreenCaptureOutput(
            success=True, 
            message="Screenshot captured successfully", 
            base64_image=b64_img
        )

@register_skill
class ScreenInfoSkill(BaseSkill):
    spec = SkillSpec(
        name="computer.screen.info",
        description="Get screen resolution and current cursor position. 获取屏幕分辨率和鼠标位置。",
        input_model=ScreenInfoInput,
        output_model=ScreenInfoOutput,
        side_effects=set(),
        risk_level=SkillRiskLevel.READ,
        aliases=["screen.info", "get_screen_size"],
    )

    async def run(self, ctx: "SkillContext", input_data: ScreenInfoInput) -> ScreenInfoOutput:
        driver = ScreenDriver()
        info = driver.get_screen_info()
        return ScreenInfoOutput(
            success=True, 
            message="Retrieved screen info", 
            info=info
        )

