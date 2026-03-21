# server/app/avatar/skills/core/state.py

from __future__ import annotations

import logging
from typing import Optional, Any
from pydantic import Field

from ..base import BaseSkill, SkillSpec, SideEffect, SkillRiskLevel
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext
from app.avatar.runtime.graph.models.output_contract import SkillOutputContract, ValueKind, TransportMode
from app.services.state_service import get_state_service

logger = logging.getLogger(__name__)


# ── state.set ─────────────────────────────────────────────────────────────────

class StateSetInput(SkillInput):
    scope: str = Field(..., description="Scope: task, session, or user")
    key: str = Field(..., description="State key name")
    value: Any = Field(..., description="State value (JSON serialized)")
    ttl_seconds: Optional[int] = Field(None, description="TTL in seconds (None = never expire)")

class StateSetOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Set value")
    scope: str
    key: str

@register_skill
class StateSetSkill(BaseSkill[StateSetInput, StateSetOutput]):
    spec = SkillSpec(
        name="state.set",
        description="Set short-term state value (task/session/user scope). 设置短期状态值。",
        input_model=StateSetInput,
        output_model=StateSetOutput,
        side_effects=set(),
        risk_level=SkillRiskLevel.SAFE,
        aliases=["set_state", "save_state"],
        tags=["set", "store", "state", "设置", "状态"],
        output_contract=SkillOutputContract(value_kind=ValueKind.TEXT, transport_mode=TransportMode.INLINE),
    )

    async def run(self, ctx: SkillContext, params: StateSetInput) -> StateSetOutput:
        if ctx.dry_run:
            return StateSetOutput(success=True, message=f"[dry_run] Would set {params.scope}/{params.key}",
                                  scope=params.scope, key=params.key, output=str(params.value))
        try:
            scope_id = self._scope_id(ctx, params.scope)
            service = get_state_service()
            ok = service.set(scope=params.scope, scope_id=scope_id, key=params.key,
                             value=params.value, ttl_seconds=params.ttl_seconds)
            if not ok:
                return StateSetOutput(success=False, message="Failed to set state", scope=params.scope, key=params.key)
            return StateSetOutput(success=True, message=f"Set {params.scope}/{params.key}",
                                  scope=params.scope, key=params.key, output=str(params.value))
        except Exception as e:
            return StateSetOutput(success=False, message=str(e), scope=params.scope, key=params.key)

    def _scope_id(self, ctx, scope):
        if scope == "task":
            return ctx.execution_context.task_id if ctx.execution_context else "default"
        if scope == "session":
            return ctx.execution_context.session_id if ctx.execution_context else "default"
        return "default"


# ── state.get ─────────────────────────────────────────────────────────────────

class StateGetInput(SkillInput):
    scope: str = Field(..., description="Scope: task, session, or user")
    key: str = Field(..., description="State key name")
    default: Optional[Any] = Field(None, description="Default value if not found")

class StateGetOutput(SkillOutput):
    output: Optional[Any] = Field(None, description="Retrieved value")
    scope: str
    key: str
    value: Optional[Any] = None
    found: bool = False

@register_skill
class StateGetSkill(BaseSkill[StateGetInput, StateGetOutput]):
    spec = SkillSpec(
        name="state.get",
        description="Get short-term state value. 获取短期状态值。",
        input_model=StateGetInput,
        output_model=StateGetOutput,
        side_effects=set(),
        risk_level=SkillRiskLevel.SAFE,
        aliases=["get_state", "load_state"],
        tags=["get", "load", "state", "获取", "状态"],
        output_contract=SkillOutputContract(value_kind=ValueKind.JSON, transport_mode=TransportMode.INLINE),
    )

    async def run(self, ctx: SkillContext, params: StateGetInput) -> StateGetOutput:
        if ctx.dry_run:
            return StateGetOutput(success=True, message=f"[dry_run] Would get {params.scope}/{params.key}",
                                  scope=params.scope, key=params.key, value=params.default, output=params.default)
        try:
            scope_id = self._scope_id(ctx, params.scope)
            service = get_state_service()
            value = service.get(scope=params.scope, scope_id=scope_id, key=params.key, default=params.default)
            found = value != params.default
            return StateGetOutput(success=True, message=f"Got {params.scope}/{params.key}",
                                  scope=params.scope, key=params.key, value=value, found=found, output=value)
        except Exception as e:
            return StateGetOutput(success=False, message=str(e), scope=params.scope, key=params.key,
                                  value=params.default, output=params.default)

    def _scope_id(self, ctx, scope):
        if scope == "task":
            return ctx.execution_context.task_id if ctx.execution_context else "default"
        if scope == "session":
            return ctx.execution_context.session_id if ctx.execution_context else "default"
        return "default"


# ── state.delete ──────────────────────────────────────────────────────────────

class StateDeleteInput(SkillInput):
    scope: str = Field(..., description="Scope: task, session, or user")
    key: str = Field(..., description="State key name")

class StateDeleteOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Deleted key")
    scope: str
    key: str

@register_skill
class StateDeleteSkill(BaseSkill[StateDeleteInput, StateDeleteOutput]):
    spec = SkillSpec(
        name="state.delete",
        description="Delete state value. 删除状态值。",
        input_model=StateDeleteInput,
        output_model=StateDeleteOutput,
        side_effects=set(),
        risk_level=SkillRiskLevel.SAFE,
        aliases=["delete_state", "remove_state"],
        tags=["delete", "remove", "state", "删除", "状态"],
        output_contract=SkillOutputContract(value_kind=ValueKind.TEXT, transport_mode=TransportMode.INLINE),
    )

    async def run(self, ctx: SkillContext, params: StateDeleteInput) -> StateDeleteOutput:
        if ctx.dry_run:
            return StateDeleteOutput(success=True, message=f"[dry_run] Would delete {params.scope}/{params.key}",
                                     scope=params.scope, key=params.key, output=params.key)
        try:
            scope_id = self._scope_id(ctx, params.scope)
            service = get_state_service()
            ok = service.delete(scope=params.scope, scope_id=scope_id, key=params.key)
            if not ok:
                return StateDeleteOutput(success=False, message="Failed to delete state", scope=params.scope, key=params.key)
            return StateDeleteOutput(success=True, message=f"Deleted {params.scope}/{params.key}",
                                     scope=params.scope, key=params.key, output=params.key)
        except Exception as e:
            return StateDeleteOutput(success=False, message=str(e), scope=params.scope, key=params.key)

    def _scope_id(self, ctx, scope):
        if scope == "task":
            return ctx.execution_context.task_id if ctx.execution_context else "default"
        if scope == "session":
            return ctx.execution_context.session_id if ctx.execution_context else "default"
        return "default"
