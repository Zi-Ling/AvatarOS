# app/avatar/skills/builtin/computer/keyboard.py

from pydantic import BaseModel, Field
from typing import List, Optional, Union
from ...base import BaseSkill, SkillSpec, SkillOutput, SkillCategory, SkillMetadata, SkillDomain, SkillCapability
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
        api_name="computer.keyboard.type",
        internal_name="computer.keyboard.type_v1",
        aliases=["keyboard.type", "type_text", "input_text", "keyboard_input", "write_text"],
        description="Type text string using the keyboard simulation. Use this to input text into active windows. 使用键盘模拟输入文本。",
        category=SkillCategory.COMPUTER,
        input_model=KeyboardTypeInput,
        output_model=SkillOutput,
        
        # Capability Routing
        meta=SkillMetadata(
            domain=SkillDomain.UI,
            capabilities={SkillCapability.WRITE},
            risk_level="normal"
        ),
        
        synonyms=[
            "type string",
            "input text",
            "write with keyboard",
            "simulate typing",
            "输入文本",
            "键盘打字",
            "模拟输入"
        ],
        tags=["computer", "keyboard", "input", "键盘", "输入", "打字"]
    )

    async def run(self, ctx: "SkillContext", input_data: KeyboardTypeInput) -> SkillOutput:
        driver = KeyboardDriver()
        driver.type_text(input_data.text, input_data.interval)
        return SkillOutput(success=True, message=f"Typed text: {input_data.text[:50]}...")

@register_skill
class KeyboardHotkeySkill(BaseSkill):
    spec = SkillSpec(
        name="computer.keyboard.hotkey",
        api_name="computer.keyboard.hotkey",
        internal_name="computer.keyboard.hotkey_v1",
        aliases=["keyboard.hotkey", "hotkey", "press_combo"],
        description="Press a combination of keys simultaneously (e.g. Ctrl+C). 按下组合键（如Ctrl+C）。",
        category=SkillCategory.COMPUTER,
        input_model=KeyboardHotkeyInput,
        output_model=SkillOutput,
        
        # Capability Routing
        meta=SkillMetadata(
            domain=SkillDomain.UI,
            capabilities={SkillCapability.EXECUTE, SkillCapability.WRITE}, # Hotkeys often execute actions or edit
            risk_level="normal"
        ),
        
        synonyms=[
            "press shortcut",
            "keyboard combo",
            "hotkey press",
            "send keys",
            "按组合键",
            "快捷键",
            "热键"
        ],
        tags=["computer", "keyboard", "hotkey", "键盘", "快捷键", "组合键"]
    )

    async def run(self, ctx: "SkillContext", input_data: KeyboardHotkeyInput) -> SkillOutput:
        driver = KeyboardDriver()
        driver.hotkey(*input_data.keys)
        return SkillOutput(success=True, message=f"Executed hotkey: {'+'.join(input_data.keys)}")
