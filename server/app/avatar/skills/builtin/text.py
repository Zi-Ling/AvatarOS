# app/avatar/skills/builtin/text.py

from __future__ import annotations

import re
from typing import List, Optional
from pydantic import Field

from ..base import BaseSkill, SkillSpec, SkillCategory, SkillMetadata, SkillDomain, SkillCapability
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext


# ============================================================================
# text.replace
# ============================================================================

class TextReplaceInput(SkillInput):
    text: str = Field(..., description="Original text.")
    old: str = Field(..., description="Substring to replace.")
    new: str = Field(..., description="Replacement string.")
    count: int = Field(-1, description="Max replacements (-1 for all).")

class TextReplaceOutput(SkillOutput):
    result: str
    count: int

@register_skill
class TextReplaceSkill(BaseSkill[TextReplaceInput, TextReplaceOutput]):
    spec = SkillSpec(
        name="text.replace",
        api_name="text.replace",
        aliases=["str.replace", "string.replace"],
        description="Replace occurrences of a substring in text. 替换文本中的字符串。",
        category=SkillCategory.OTHER,
        input_model=TextReplaceInput,
        output_model=TextReplaceOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.COMPUTE,
            capabilities={SkillCapability.MODIFY},
            risk_level="low"
        ),
        
        synonyms=[
            "replace string",
            "substitute text",
            "替换字符串",
            "替换文本"
        ],
        examples=[
            {"description": "Replace text", "params": {"text": "Hello World", "old": "World", "new": "Python"}}
        ],
        tags=["text", "string", "文本", "替换", "字符串"]
    )

    async def run(self, ctx: SkillContext, params: TextReplaceInput) -> TextReplaceOutput:
        replaced = params.text.replace(params.old, params.new, params.count)
        return TextReplaceOutput(
            success=True,
            message="Text replaced.",
            result=replaced,
            count=params.text.count(params.old) if params.count == -1 else min(params.count, params.text.count(params.old))
        )


# ============================================================================
# text.regex_extract
# ============================================================================

class RegexExtractInput(SkillInput):
    text: str = Field(..., description="Text to search in.")
    pattern: str = Field(..., description="Regex pattern.")
    flags: str = Field("", description="Regex flags (IGNORECASE|MULTILINE|DOTALL).")

class RegexExtractOutput(SkillOutput):
    matches: List[str]

@register_skill
class TextRegexExtractSkill(BaseSkill[RegexExtractInput, RegexExtractOutput]):
    spec = SkillSpec(
        name="text.regex_extract",
        api_name="text.regex_extract",
        aliases=["regex.match", "regex.find"],
        description="Extract matches from text using regex. 使用正则表达式提取文本内容。",
        category=SkillCategory.OTHER,
        input_model=RegexExtractInput,
        output_model=RegexExtractOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.COMPUTE,
            capabilities={SkillCapability.READ, SkillCapability.SEARCH},
            risk_level="low"
        ),
        
        synonyms=[
            "regex match",
            "find pattern",
            "extract pattern",
            "正则匹配",
            "提取模式",
            "查找模式"
        ],
        examples=[
            {"description": "Extract email addresses", "params": {"text": "Contact: user@example.com", "pattern": r"\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Z|a-z]{2,}\\b"}}
        ],
        tags=["text", "regex", "文本", "提取", "正则"]
    )

    async def run(self, ctx: SkillContext, params: RegexExtractInput) -> RegexExtractOutput:
        flags = 0
        if params.flags:
            flag_map = {
                "IGNORECASE": re.IGNORECASE,
                "MULTILINE": re.MULTILINE,
                "DOTALL": re.DOTALL,
            }
            for part in params.flags.split("|"):
                part = part.strip().upper()
                if part in flag_map:
                    flags |= flag_map[part]

        try:
            regex = re.compile(params.pattern, flags=flags)
            matches = regex.findall(params.text)
            return RegexExtractOutput(
                success=True,
                message=f"Found {len(matches)} matches.",
                matches=matches
            )
        except re.error as e:
            return RegexExtractOutput(success=False, message=f"Invalid regex: {e}", matches=[])
