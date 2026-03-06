# server/app/avatar/skills/core/state.py

from __future__ import annotations

import logging
from typing import Optional, Any
from pydantic import Field

from ..base import BaseSkill, SkillSpec, SkillCategory, SkillPermission, SkillMetadata, SkillDomain, SkillCapability, SkillRiskLevel
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext
from app.services.state_service import get_state_service

logger = logging.getLogger(__name__)


# ============================================================================
# state.set - 设置状态
# ============================================================================

class StateSetInput(SkillInput):
    scope: str = Field(..., description="Scope type: task, session, or user")
    key: str = Field(..., description="State key name")
    value: Any = Field(..., description="State value (will be JSON serialized)")
    ttl_seconds: Optional[int] = Field(None, description="Time to live in seconds (None = never expire)")

class StateSetOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Primary output: set value")
    scope: str
    key: str

@register_skill
class StateSetSkill(BaseSkill[StateSetInput, StateSetOutput]):
    spec = SkillSpec(
        name="state.set",
        api_name="state.set",
        aliases=["set_state", "save_state"],
        description="Set short-term state value (task/session/user scope). 设置短期状态值。",
        category=SkillCategory.SYSTEM,
        input_model=StateSetInput,
        output_model=StateSetOutput,
        
        meta=SkillMetadata(
            domain=SkillDomain.SYSTEM,
            capabilities={SkillCapability.WRITE},
            risk_level=SkillRiskLevel.SAFE,
            priority=10,
        ),
        
        synonyms=["save state", "store state", "set variable", "保存状态", "存储状态"],
        
        examples=[
            {"description": "Save task state", "params": {"scope": "task", "key": "counter", "value": 42}},
            {"description": "Save with TTL", "params": {"scope": "session", "key": "temp_data", "value": "test", "ttl_seconds": 3600}},
        ],
        
        permissions=[SkillPermission(name="state_write", description="Write state")],
        tags=["state", "storage", "状态", "存储"]
    )

    async def run(self, ctx: SkillContext, params: StateSetInput) -> StateSetOutput:
        if ctx.dry_run:
            return StateSetOutput(
                success=True,
                message=f"[dry_run] Would set state: {params.scope}/{params.key}",
                scope=params.scope,
                key=params.key,
                output=str(params.value)
            )

        try:
            # 获取 scope_id
            scope_id = self._get_scope_id(ctx, params.scope)
            
            # 设置状态
            service = get_state_service()
            success = service.set(
                scope=params.scope,
                scope_id=scope_id,
                key=params.key,
                value=params.value,
                ttl_seconds=params.ttl_seconds
            )
            
            if not success:
                return StateSetOutput(
                    success=False,
                    message="Failed to set state",
                    scope=params.scope,
                    key=params.key,
                    output=None
                )
            
            return StateSetOutput(
                success=True,
                message=f"State set: {params.scope}/{params.key}",
                scope=params.scope,
                key=params.key,
                output=str(params.value)
            )
        
        except Exception as e:
            return StateSetOutput(
                success=False,
                message=str(e),
                scope=params.scope,
                key=params.key,
                output=None
            )
    
    def _get_scope_id(self, ctx: SkillContext, scope: str) -> str:
        """根据 scope 类型获取对应的 ID"""
        if scope == "task":
            return ctx.execution_context.task_id if ctx.execution_context else "default"
        elif scope == "session":
            return ctx.execution_context.session_id if ctx.execution_context else "default"
        elif scope == "user":
            return "default_user"  # TODO: 从 ctx 获取真实 user_id
        else:
            return "default"


# ============================================================================
# state.get - 获取状态
# ============================================================================

class StateGetInput(SkillInput):
    scope: str = Field(..., description="Scope type: task, session, or user")
    key: str = Field(..., description="State key name")
    default: Optional[Any] = Field(None, description="Default value if not found")

class StateGetOutput(SkillOutput):
    output: Optional[Any] = Field(None, description="Primary output: retrieved value")
    scope: str
    key: str
    value: Optional[Any] = None
    found: bool = False

@register_skill
class StateGetSkill(BaseSkill[StateGetInput, StateGetOutput]):
    spec = SkillSpec(
        name="state.get",
        api_name="state.get",
        aliases=["get_state", "load_state"],
        description="Get short-term state value. 获取短期状态值。",
        category=SkillCategory.SYSTEM,
        input_model=StateGetInput,
        output_model=StateGetOutput,
        
        meta=SkillMetadata(
            domain=SkillDomain.SYSTEM,
            capabilities={SkillCapability.READ},
            risk_level=SkillRiskLevel.SAFE,
            priority=10,
        ),
        
        synonyms=["load state", "retrieve state", "get variable", "读取状态", "获取状态"],
        
        examples=[
            {"description": "Get task state", "params": {"scope": "task", "key": "counter"}},
            {"description": "Get with default", "params": {"scope": "session", "key": "temp_data", "default": "fallback"}},
        ],
        
        permissions=[SkillPermission(name="state_read", description="Read state")],
        tags=["state", "storage", "状态", "读取"]
    )

    async def run(self, ctx: SkillContext, params: StateGetInput) -> StateGetOutput:
        if ctx.dry_run:
            return StateGetOutput(
                success=True,
                message=f"[dry_run] Would get state: {params.scope}/{params.key}",
                scope=params.scope,
                key=params.key,
                value=params.default,
                found=False,
                output=params.default
            )

        try:
            # 获取 scope_id
            scope_id = self._get_scope_id(ctx, params.scope)
            
            # 获取状态
            service = get_state_service()
            value = service.get(
                scope=params.scope,
                scope_id=scope_id,
                key=params.key,
                default=params.default
            )
            
            found = value != params.default
            
            return StateGetOutput(
                success=True,
                message=f"State retrieved: {params.scope}/{params.key}",
                scope=params.scope,
                key=params.key,
                value=value,
                found=found,
                output=value
            )
        
        except Exception as e:
            return StateGetOutput(
                success=False,
                message=str(e),
                scope=params.scope,
                key=params.key,
                value=params.default,
                found=False,
                output=params.default
            )
    
    def _get_scope_id(self, ctx: SkillContext, scope: str) -> str:
        """根据 scope 类型获取对应的 ID"""
        if scope == "task":
            return ctx.execution_context.task_id if ctx.execution_context else "default"
        elif scope == "session":
            return ctx.execution_context.session_id if ctx.execution_context else "default"
        elif scope == "user":
            return "default_user"
        else:
            return "default"


# ============================================================================
# state.delete - 删除状态
# ============================================================================

class StateDeleteInput(SkillInput):
    scope: str = Field(..., description="Scope type: task, session, or user")
    key: str = Field(..., description="State key name")

class StateDeleteOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Primary output: deleted key")
    scope: str
    key: str

@register_skill
class StateDeleteSkill(BaseSkill[StateDeleteInput, StateDeleteOutput]):
    spec = SkillSpec(
        name="state.delete",
        api_name="state.delete",
        aliases=["delete_state", "remove_state"],
        description="Delete state value. 删除状态值。",
        category=SkillCategory.SYSTEM,
        input_model=StateDeleteInput,
        output_model=StateDeleteOutput,
        
        meta=SkillMetadata(
            domain=SkillDomain.SYSTEM,
            capabilities={SkillCapability.DELETE},
            risk_level=SkillRiskLevel.SAFE,
            priority=10,
        ),
        
        synonyms=["remove state", "clear state", "删除状态", "清除状态"],
        
        examples=[
            {"description": "Delete task state", "params": {"scope": "task", "key": "counter"}},
        ],
        
        permissions=[SkillPermission(name="state_write", description="Delete state")],
        tags=["state", "storage", "状态", "删除"]
    )

    async def run(self, ctx: SkillContext, params: StateDeleteInput) -> StateDeleteOutput:
        if ctx.dry_run:
            return StateDeleteOutput(
                success=True,
                message=f"[dry_run] Would delete state: {params.scope}/{params.key}",
                scope=params.scope,
                key=params.key,
                output=params.key
            )

        try:
            # 获取 scope_id
            scope_id = self._get_scope_id(ctx, params.scope)
            
            # 删除状态
            service = get_state_service()
            success = service.delete(
                scope=params.scope,
                scope_id=scope_id,
                key=params.key
            )
            
            if not success:
                return StateDeleteOutput(
                    success=False,
                    message="Failed to delete state",
                    scope=params.scope,
                    key=params.key,
                    output=None
                )
            
            return StateDeleteOutput(
                success=True,
                message=f"State deleted: {params.scope}/{params.key}",
                scope=params.scope,
                key=params.key,
                output=params.key
            )
        
        except Exception as e:
            return StateDeleteOutput(
                success=False,
                message=str(e),
                scope=params.scope,
                key=params.key,
                output=None
            )
    
    def _get_scope_id(self, ctx: SkillContext, scope: str) -> str:
        """根据 scope 类型获取对应的 ID"""
        if scope == "task":
            return ctx.execution_context.task_id if ctx.execution_context else "default"
        elif scope == "session":
            return ctx.execution_context.session_id if ctx.execution_context else "default"
        elif scope == "user":
            return "default_user"
        else:
            return "default"
