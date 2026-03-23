# app/avatar/skills/builtin/computer/keyboard.py

from pydantic import BaseModel, Field
from typing import List, Optional, Union
from ...base import BaseSkill, SkillSpec, SkillOutput, SideEffect, SkillRiskLevel
from ...registry import register_skill
from ....actions.gui.drivers import KeyboardDriver

# --- Models ---
class KeyboardTypeInput(BaseModel):
    text: str = Field(..., description="Text to type")
    interval: float = Field(0.05, description="Interval between keystrokes")

class KeyboardHotkeyInput(BaseModel):
    keys: List[str] = Field(..., description="List of keys to press simultaneously (e.g. ['ctrl', 'c'])")

class KeyboardPressInput(BaseModel):
    keys: List[str] = Field(..., description="List of keys to press in sequence")
    interval: float = Field(0.1, description="Interval between key presses")

# --- Skills ---

@register_skill
class KeyboardTypeSkill(BaseSkill):
    spec = SkillSpec(
        name="computer.keyboard.type",
        description="Type text string using keyboard simulation. 使用键盘模拟输入文本。",
        input_model=KeyboardTypeInput,
        output_model=SkillOutput,
        side_effects=set(),
        risk_level=SkillRiskLevel.WRITE,
        aliases=["keyboard.type", "type_text", "input_text", "write_text"],
        tags=["keyboard", "type", "input", "text", "键盘", "输入", "打字"],
        requires_host_desktop=True,
    )

    async def run(self, ctx: "SkillContext", input_data: KeyboardTypeInput) -> SkillOutput:
        driver = KeyboardDriver()
        driver.type_text(input_data.text, input_data.interval)
        return SkillOutput(success=True, message=f"Typed text: {input_data.text[:50]}...")

@register_skill
class KeyboardHotkeySkill(BaseSkill):
    spec = SkillSpec(
        name="computer.keyboard.hotkey",
        description="Press a combination of keys simultaneously (e.g. Ctrl+C). 按下组合键。",
        input_model=KeyboardHotkeyInput,
        output_model=SkillOutput,
        side_effects=set(),
        risk_level=SkillRiskLevel.WRITE,
        aliases=["keyboard.hotkey", "hotkey", "press_combo"],
        tags=["keyboard", "hotkey", "shortcut", "combo", "键盘", "快捷键", "组合键"],
        requires_host_desktop=True,
    )

    async def run(self, ctx: "SkillContext", input_data: KeyboardHotkeyInput) -> SkillOutput:
        driver = KeyboardDriver()
        driver.hotkey(*input_data.keys)
        return SkillOutput(success=True, message=f"Executed hotkey: {'+'.join(input_data.keys)}")

@register_skill
class KeyboardPressSkill(BaseSkill):
    spec = SkillSpec(
        name="computer.keyboard.press",
        description="Press keys in sequence. 按顺序按下按键。",
        input_model=KeyboardPressInput,
        output_model=SkillOutput,
        side_effects=set(),
        risk_level=SkillRiskLevel.WRITE,
        aliases=["keyboard.press", "press_keys", "key_sequence"],
        tags=["keyboard", "press", "key", "键盘", "按键"],
        requires_host_desktop=True,
    )

    async def run(self, ctx: "SkillContext", input_data: KeyboardPressInput) -> SkillOutput:
        import asyncio
        driver = KeyboardDriver()
        for key in input_data.keys:
            driver.press_key(key)
            await asyncio.sleep(input_data.interval)
        return SkillOutput(success=True, message=f"Pressed keys: {input_data.keys}")
