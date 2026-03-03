# app/avatar/skills/builtin/clipboard.py

from __future__ import annotations

import pyperclip
from typing import Optional
from pydantic import Field

from ..base import BaseSkill, SkillSpec, SkillCategory, SkillMetadata, SkillDomain, SkillCapability
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext


# ============================================================================
# clipboard.copy
# ============================================================================

class ClipboardCopyInput(SkillInput):
    text: str = Field(..., description="Text to copy to clipboard.")

class ClipboardCopyOutput(SkillOutput):
    text_length: int

@register_skill
class ClipboardCopySkill(BaseSkill[ClipboardCopyInput, ClipboardCopyOutput]):
    spec = SkillSpec(
        name="clipboard.copy",
        api_name="clipboard.copy",
        aliases=["clip.copy", "copy_to_clipboard"],  # 移除 "cp" 避免与 dir.copy 冲突，使用更明确的别名
        description="Copy text to system clipboard. 复制文本到剪贴板。",
        category=SkillCategory.SYSTEM,
        input_model=ClipboardCopyInput,
        output_model=ClipboardCopyOutput,
        
        # Capability Routing
        meta=SkillMetadata(
            domain=SkillDomain.SYSTEM,
            capabilities={SkillCapability.WRITE},
            risk_level="normal"
        ),
        
        synonyms=[
            "copy to clipboard",
            "copy text",
            "复制到剪贴板",
            "复制文本"
        ],
        tags=["clipboard", "copy", "剪贴板", "复制"]
    )

    async def run(self, ctx: SkillContext, params: ClipboardCopyInput) -> ClipboardCopyOutput:
        if ctx.dry_run:
            return ClipboardCopyOutput(success=True, message="[dry_run] Copied", text_length=len(params.text))

        try:
            pyperclip.copy(params.text)
            return ClipboardCopyOutput(success=True, message="Copied to clipboard", text_length=len(params.text))
        except Exception as e:
            return ClipboardCopyOutput(success=False, message=str(e), text_length=0)


# ============================================================================
# clipboard.paste
# ============================================================================

class ClipboardPasteInput(SkillInput):
    pass # No params

class ClipboardPasteOutput(SkillOutput):
    text: str
    text_length: int

@register_skill
class ClipboardPasteSkill(BaseSkill[ClipboardPasteInput, ClipboardPasteOutput]):
    spec = SkillSpec(
        name="clipboard.paste",
        api_name="clipboard.paste",
        aliases=["clip.paste", "paste_from_clipboard"],  # 使用更明确的别名
        description="Read text from system clipboard. 从剪贴板读取文本。",
        category=SkillCategory.SYSTEM,
        input_model=ClipboardPasteInput,
        output_model=ClipboardPasteOutput,
        
        # Capability Routing
        meta=SkillMetadata(
            domain=SkillDomain.SYSTEM,
            capabilities={SkillCapability.READ},
            risk_level="normal"
        ),
        
        synonyms=[
            "paste from clipboard",
            "get clipboard",
            "从剪贴板粘贴",
            "获取剪贴板内容"
        ],
        tags=["clipboard", "paste", "剪贴板", "粘贴"]
    )

    async def run(self, ctx: SkillContext, params: ClipboardPasteInput) -> ClipboardPasteOutput:
        if ctx.dry_run:
            return ClipboardPasteOutput(success=True, message="[dry_run] Pasted", text="", text_length=0)

        try:
            text = pyperclip.paste() or ""
            return ClipboardPasteOutput(success=True, message="Pasted from clipboard", text=text, text_length=len(text))
        except Exception as e:
            return ClipboardPasteOutput(success=False, message=str(e), text="", text_length=0)
