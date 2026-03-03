# app/avatar/skills/builtin/schedule.py
from __future__ import annotations

from pydantic import Field
from ..base import BaseSkill, SkillSpec, SkillCategory, SkillPermission, SkillMetadata, SkillDomain, SkillCapability
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext
from app.services.scheduler_service import scheduler_service

class CreateScheduleInput(SkillInput):
    name: str = Field(..., description="Name of the scheduled task")
    cron: str = Field(..., description="Cron expression (e.g. '0 9 * * *'). For daily at 9am use '0 9 * * *'.")
    task_goal: str = Field(..., description="The goal description of the task to execute (e.g. 'Check stock price').")

class CreateScheduleOutput(SkillOutput):
    schedule_id: str
    message: str

@register_skill
class CreateScheduleSkill(BaseSkill[CreateScheduleInput, CreateScheduleOutput]):
    spec = SkillSpec(
        name="system.schedule.create",
        api_name="schedule.create",
        aliases=["create_schedule", "add_schedule", "set_reminder", "add_cron_job"],
        description="Create a new recurring scheduled task (cron job). Use this when user says 'every day', 'daily', 'at 9am', etc. 创建定时任务或日程提醒。",
        category=SkillCategory.SYSTEM,
        input_model=CreateScheduleInput,
        output_model=CreateScheduleOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.SYSTEM,
            capabilities={SkillCapability.CREATE},
            risk_level="normal"
        ),
        
        permissions=[SkillPermission(name="schedule_manage", description="Manage schedules")],
        synonyms=[
            "创建日程",
            "设置定时任务",
            "每天执行",
            "每小时执行",
            "提醒我",
            "schedule task",
            "recurring task"
        ],
        examples=[
            {"description": "Create daily schedule", "params": {"name": "Daily check", "cron": "0 9 * * *", "task_goal": "Check stock price"}}
        ],
        tags=["system", "schedule", "cron", "timer", "定时", "日程", "提醒", "任务"]
    )

    async def run(self, ctx: SkillContext, params: CreateScheduleInput) -> CreateScheduleOutput:
        if ctx.dry_run:
            return CreateScheduleOutput(
                success=True, 
                message=f"[dry_run] Would schedule '{params.name}' at '{params.cron}' to do '{params.task_goal}'",
                schedule_id="dry_run_id"
            )

        # Construct a minimal intent dict to be stored
        intent_spec = {
            "goal": params.task_goal,
            "intent_type": "unknown", # Will be re-extracted at runtime
            "domain": "other",
            "params": {},
            "metadata": {
                "source": "scheduler"
            }
        }
        
        try:
            s = scheduler_service.create_schedule(params.name, params.cron, intent_spec)
            return CreateScheduleOutput(
                success=True,
                schedule_id=s.id,
                message=f"Successfully scheduled '{params.name}' (ID: {s.id[:8]}) to run at '{params.cron}'"
            )
        except Exception as e:
             return CreateScheduleOutput(
                success=False,
                schedule_id="",
                message=f"Failed to create schedule: {str(e)}"
            )

