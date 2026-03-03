# app/avatar/skills/builtin/time.py

from __future__ import annotations

import time
import asyncio
from datetime import datetime, timezone
from typing import Optional
from pydantic import Field

from ..base import BaseSkill, SkillSpec, SkillCategory, SkillMetadata, SkillDomain, SkillCapability
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext


# ============================================================================
# time.now
# ============================================================================

class TimeNowInput(SkillInput):
    pass # No params

class TimeNowOutput(SkillOutput):
    now_utc_iso: str

@register_skill
class TimeNowSkill(BaseSkill[TimeNowInput, TimeNowOutput]):
    spec = SkillSpec(
        name="time.now",
        api_name="time.now",
        internal_name="time.now_v1",
        aliases=["date.now", "now", "time.get"], # Added time.get
        description="Get current system time. Use this whenever the user asks for time. 获取当前系统时间/查询系统时间。",
        category=SkillCategory.SYSTEM,
        input_model=TimeNowInput,
        output_model=TimeNowOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.SYSTEM,
            capabilities={SkillCapability.READ},
            risk_level="low"
        ),
        
        synonyms=[
            "get current time",
            "current date",
            "what time is it",
            "获取当前时间",
            "现在几点",
            "当前日期"
        ],
        examples=[
            {"description": "Get current time", "params": {}}
        ],
        tags=["time", "date", "时间", "日期", "当前时间"]
    )

    async def run(self, ctx: SkillContext, params: TimeNowInput) -> TimeNowOutput:
        try:
            # Execute
            now = datetime.now(timezone.utc).isoformat()
            
            # Post-execution verification
            if not now:
                return TimeNowOutput(success=False, message="Verification Failed: Time string is empty", now_utc_iso="")
            
            # Verify ISO format (basic check)
            if 'T' not in now or len(now) < 19:
                return TimeNowOutput(success=False, message=f"Verification Failed: Invalid ISO format: {now}", now_utc_iso=now)
            
            # Verify it's a reasonable year (2020-2100)
            try:
                year = int(now[:4])
                if year < 2020 or year > 2100:
                    return TimeNowOutput(success=False, message=f"Verification Failed: Unreasonable year: {year}", now_utc_iso=now)
            except ValueError:
                return TimeNowOutput(success=False, message=f"Verification Failed: Cannot parse year from: {now}", now_utc_iso=now)
            
            return TimeNowOutput(
                success=True,
                message=f"Current time: {now}",
                now_utc_iso=now
            )
        except Exception as e:
            return TimeNowOutput(success=False, message=f"Failed to get time: {str(e)}", now_utc_iso="")


# ============================================================================
# time.sleep
# ============================================================================

class TimeSleepInput(SkillInput):
    seconds: float = Field(..., description="Number of seconds to sleep.")

class TimeSleepOutput(SkillOutput):
    seconds: float

@register_skill
class TimeSleepSkill(BaseSkill[TimeSleepInput, TimeSleepOutput]):
    spec = SkillSpec(
        name="time.sleep",
        api_name="time.sleep",
        internal_name="time.sleep_v1",
        aliases=["sleep", "wait", "delay"],
        description="Sleep for a given number of seconds. 等待指定秒数。",
        category=SkillCategory.OTHER,
        input_model=TimeSleepInput,
        output_model=TimeSleepOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.SYSTEM,
            capabilities=set(),
            risk_level="low"
        ),
        
        synonyms=[
            "wait seconds",
            "delay execution",
            "暂停执行",
            "等待",
            "延迟"
        ],
        examples=[
            {"description": "Sleep for 5 seconds", "params": {"seconds": 5.0}}
        ],
        tags=["time", "delay", "等待", "延迟", "暂停"]
    )

    async def run(self, ctx: SkillContext, params: TimeSleepInput) -> TimeSleepOutput:
        if ctx.dry_run:
            return TimeSleepOutput(
                success=True,
                message=f"[dry_run] Would sleep for {params.seconds}s",
                seconds=params.seconds
            )

        try:
            # Using asyncio.sleep instead of time.sleep for async compatibility
            await asyncio.sleep(params.seconds)
            return TimeSleepOutput(
                success=True,
                message=f"Slept for {params.seconds}s",
                seconds=params.seconds
            )
        except Exception as e:
             return TimeSleepOutput(success=False, message=str(e), seconds=params.seconds)


# ============================================================================
# time.format_now
# ============================================================================

class TimeFormatInput(SkillInput):
    format: str = Field(default="%Y-%m-%d %H:%M:%S",
                        description="strftime format string, e.g. '%Y-%m-%d %H:%M:%S'.")


class TimeFormatOutput(SkillOutput):
    value: str
    format: str

@register_skill
class TimeFormatNowSkill(BaseSkill[TimeFormatInput, TimeFormatOutput]):
    spec = SkillSpec(
        name="time.format_now",
        api_name="time.format",
        internal_name="time.format_v1",
        aliases=["date.format", "strftime"],
        description="Format current local time with given strftime format string. 格式化当前时间。",
        category=SkillCategory.OTHER,
        input_model=TimeFormatInput,
        output_model=TimeFormatOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.SYSTEM,
            capabilities={SkillCapability.READ},
            risk_level="low"
        ),
        
        synonyms=[
            "format time",
            "format date",
            "格式化时间",
            "格式化日期"
        ],
        examples=[
            {"description": "Format time", "params": {"format": "%Y-%m-%d %H:%M:%S"}}
        ],
        tags=["time", "format", "时间", "格式化", "日期"]
    )

    async def run(self, ctx: SkillContext, params: TimeFormatInput) -> TimeFormatOutput:
        try:
            now = datetime.now()
            formatted = now.strftime(params.format)
            return TimeFormatOutput(
                success=True,
                message="Formatted current time.",
                value=formatted,
                format=params.format
            )
        except Exception as e:
            return TimeFormatOutput(success=False, message=str(e), value="", format=params.format)
