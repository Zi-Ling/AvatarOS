"""NodeRunner ↔ ActionPlane integration adapter.

Provides:
  - auto_wrap_skills(): wraps all skills in skill_registry as ActionExecutors
  - ActionPlaneNodeProxy: optional proxy that NodeRunner can delegate to

Requirements: 8.1, 8.6
"""
from __future__ import annotations

import logging
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.avatar.runtime.action_plane.action_plane import ActionPlane

logger = logging.getLogger(__name__)


def auto_wrap_skills(action_plane: ActionPlane) -> int:
    """Wrap all skills in the global skill_registry as ActionExecutors
    and register them to the given ActionPlane.

    Returns the number of executors registered.
    """
    from app.avatar.skills.registry import skill_registry
    from app.avatar.runtime.action_plane.action_executor import SkillActionExecutor

    count = 0
    for skill_cls in skill_registry.iter_skills():
        try:
            executor = SkillActionExecutor(skill_cls)
            action_plane.register(executor)
            count += 1
        except Exception as e:
            logger.warning(
                "[ActionPlaneAdapter] Failed to wrap skill %s: %s",
                getattr(skill_cls, "spec", {}).name if hasattr(skill_cls, "spec") else "?",
                e,
            )
    logger.info("[ActionPlaneAdapter] Registered %d skill executors", count)
    return count


class ActionPlaneNodeProxy:
    """Proxy that NodeRunner can use to forward execution through ActionPlane.

    When ActionPlane is available (feature flag enabled), NodeRunner delegates
    skill execution through this proxy. When unavailable, NodeRunner falls back
    to its existing direct execution path.
    """

    def __init__(self, action_plane: ActionPlane) -> None:
        self._action_plane = action_plane

    async def execute_skill(
        self,
        skill_name: str,
        params: dict[str, Any],
        requester_id: str = "node_runner",
    ) -> Any:
        """Execute a skill through ActionPlane governance.

        Returns the execution output on success.
        Raises RuntimeError on denial or failure.
        """
        from app.avatar.runtime.action_plane.action_plane import ActionRequest
        from app.avatar.runtime.action_plane.permission import PermissionTier

        # Determine required permission from the registered executor
        executor_id = f"skill:{skill_name}"
        executor = self._action_plane.get_executor(executor_id)
        permission_required = (
            executor.permission_tier if executor else PermissionTier.READ_ONLY
        )

        request = ActionRequest(
            executor_id=executor_id,
            action_type=skill_name,
            params=params,
            requester_id=requester_id,
            permission_required=permission_required,
        )

        result = await self._action_plane.execute(request)

        if result.status == "denied":
            raise RuntimeError(f"ActionPlane denied: {result.error}")
        if result.status == "failed":
            raise RuntimeError(f"ActionPlane execution failed: {result.error}")

        return result.output
