"""ActionExecutor Protocol + SkillActionExecutor governance wrapper.

Requirements: 8.2, 8.6
"""
from __future__ import annotations

import logging
from typing import Any, Protocol, Type, runtime_checkable

from .permission import PermissionTier

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ActionExecutor Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class ActionExecutor(Protocol):
    """Unified executor interface for ActionPlane governance."""

    @property
    def executor_id(self) -> str: ...

    @property
    def executor_type(self) -> str: ...

    @property
    def permission_tier(self) -> PermissionTier: ...

    @property
    def capabilities(self) -> list[str]: ...

    @property
    def requires_approval(self) -> bool: ...

    async def execute(self, params: dict[str, Any]) -> Any: ...


# ---------------------------------------------------------------------------
# SideEffect → PermissionTier inference
# ---------------------------------------------------------------------------

def _infer_permission_tier(side_effects: set) -> PermissionTier:
    """Infer PermissionTier from a Skill's SideEffect declarations.

    Mapping (highest wins):
      EXEC / SHELL  → write_destructive
      FS / BROWSER   → write_safe
      NETWORK / HUMAN → write_safe
      no side effects → read_only
    """
    from app.avatar.skills.base import SideEffect

    if not side_effects:
        return PermissionTier.READ_ONLY

    # Destructive side effects
    destructive = {SideEffect.EXEC}
    # Safe-write side effects
    safe_write = {SideEffect.FS, SideEffect.BROWSER, SideEffect.NETWORK, SideEffect.HUMAN}

    for effect in side_effects:
        if effect in destructive:
            return PermissionTier.WRITE_DESTRUCTIVE

    for effect in side_effects:
        if effect in safe_write:
            return PermissionTier.WRITE_SAFE

    return PermissionTier.READ_ONLY


# ---------------------------------------------------------------------------
# SkillActionExecutor — governance wrapper for Skills
# ---------------------------------------------------------------------------

class SkillActionExecutor:
    """Wraps a BaseSkill class as an ActionExecutor with governance metadata.

    Auto-infers permission_tier from the Skill's SideEffect declarations:
      FS → write_safe, SHELL/EXEC → write_destructive, no side effects → read_only
    """

    def __init__(self, skill_cls: Type[Any]) -> None:
        self._skill_cls = skill_cls
        spec = skill_cls.spec
        self._executor_id: str = f"skill:{spec.name}"
        self._executor_type: str = "skill"
        self._permission_tier: PermissionTier = _infer_permission_tier(spec.side_effects)
        self._capabilities: list[str] = [spec.name] + list(spec.aliases)
        # Destructive skills require approval by default
        self._requires_approval: bool = (
            self._permission_tier >= PermissionTier.WRITE_DESTRUCTIVE
        )

    # ── Protocol properties ──

    @property
    def executor_id(self) -> str:
        return self._executor_id

    @property
    def executor_type(self) -> str:
        return self._executor_type

    @property
    def permission_tier(self) -> PermissionTier:
        return self._permission_tier

    @property
    def capabilities(self) -> list[str]:
        return list(self._capabilities)

    @property
    def requires_approval(self) -> bool:
        return self._requires_approval

    # ── Execution ──

    async def execute(self, params: dict[str, Any]) -> Any:
        """Instantiate the skill and run it with the given params.

        The caller (ActionPlane) is responsible for governance checks
        before calling this method.
        """
        from app.avatar.skills.context import SkillContext

        skill_instance = self._skill_cls()
        context = params.pop("__context__", None) or SkillContext()
        input_model = self._skill_cls.spec.input_model
        parsed_params = input_model(**params)
        result = await skill_instance.run(context, parsed_params)
        return result
