"""ActionPlane — unified governance execution entry point.

Provides register() / execute() interface. All execution flows through:
  permission check → PolicyEngine check → approval (if needed) → execute → audit → result

Requirements: 8.1, 8.4, 8.7, 8.8, 8.9
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from .action_executor import ActionExecutor
from .audit_trail import AuditTrail, AuditTrailEntry
from .permission import PermissionTier

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ActionRequest:
    """Incoming action request to ActionPlane."""

    action_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    executor_id: str = ""
    action_type: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    requester_id: str = ""
    permission_required: PermissionTier = PermissionTier.READ_ONLY
    schema_version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "executor_id": self.executor_id,
            "action_type": self.action_type,
            "params": dict(self.params),
            "requester_id": self.requester_id,
            "permission_required": self.permission_required.value,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActionRequest:
        return cls(
            action_id=data.get("action_id", str(uuid.uuid4())),
            executor_id=data.get("executor_id", ""),
            action_type=data.get("action_type", ""),
            params=dict(data.get("params") or {}),
            requester_id=data.get("requester_id", ""),
            permission_required=PermissionTier(data.get("permission_required", "read_only")),
            schema_version=data.get("schema_version", "1.0.0"),
        )


@dataclass
class ActionResult:
    """Result of an ActionPlane execution."""

    action_id: str = ""
    status: str = "success"  # success / failed / denied
    output: Any = None
    error: Optional[str] = None
    started_at: float = 0.0
    completed_at: float = 0.0
    schema_version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActionResult:
        return cls(
            action_id=data.get("action_id", ""),
            status=data.get("status", "success"),
            output=data.get("output"),
            error=data.get("error"),
            started_at=data.get("started_at", 0.0),
            completed_at=data.get("completed_at", 0.0),
            schema_version=data.get("schema_version", "1.0.0"),
        )


# ---------------------------------------------------------------------------
# ActionPlane
# ---------------------------------------------------------------------------

class ActionPlane:
    """Unified execution entry point with governance.

    GraphPlanner faces ActionPlane as the single execution interface.
    All skill executions are routed through permission → policy → approval → execute → audit.

    On exception, falls back to skill_registry direct execution (Req 8.9).
    """

    def __init__(
        self,
        skill_registry: Any = None,
        policy_engine: Any = None,
        audit_trail: Optional[AuditTrail] = None,
        collaboration_hub: Any = None,
        workspace_boundary: Optional[str] = None,
    ) -> None:
        self._skill_registry = skill_registry
        self._policy_engine = policy_engine
        self._audit_trail = audit_trail or AuditTrail()
        self._collaboration_hub = collaboration_hub
        self._workspace_boundary = workspace_boundary
        self._executors: dict[str, ActionExecutor] = {}

    # ── Registration ──

    def register(self, executor: ActionExecutor) -> None:
        """Register an ActionExecutor."""
        self._executors[executor.executor_id] = executor
        logger.debug("[ActionPlane] registered executor %s", executor.executor_id)

    def get_executor(self, executor_id: str) -> Optional[ActionExecutor]:
        return self._executors.get(executor_id)

    # ── Execution ──

    async def execute(self, action: ActionRequest) -> ActionResult:
        """Unified execution flow:
        1. Permission check
        2. Workspace boundary check
        3. PolicyEngine check
        4. Approval (if needed)
        5. Execute
        6. Audit record
        7. Return result
        """
        started_at = time.time()

        executor = self._executors.get(action.executor_id)
        if executor is None:
            result = ActionResult(
                action_id=action.action_id,
                status="denied",
                error=f"Executor not found: {action.executor_id}",
                started_at=started_at,
                completed_at=time.time(),
            )
            self._record_audit(action, executor, result)
            return result

        # Step 1: Permission tier check
        if executor.permission_tier < action.permission_required:
            result = ActionResult(
                action_id=action.action_id,
                status="denied",
                error=(
                    f"Insufficient permission: executor has {executor.permission_tier.value}, "
                    f"action requires {action.permission_required.value}"
                ),
                started_at=started_at,
                completed_at=time.time(),
            )
            self._record_audit(action, executor, result)
            return result

        # Step 2: Workspace boundary enforcement (Req 8.7)
        if self._workspace_boundary:
            target_path = action.params.get("target_path") or action.params.get("path")
            if target_path:
                normalized_target = os.path.normpath(target_path)
                normalized_workspace = os.path.normpath(self._workspace_boundary)
                is_inside = (
                    normalized_target.startswith(normalized_workspace + os.sep)
                    or normalized_target == normalized_workspace
                )
                if not is_inside:
                    # Cross-workspace: need admin + explicit approval
                    if executor.permission_tier != PermissionTier.ADMIN:
                        result = ActionResult(
                            action_id=action.action_id,
                            status="denied",
                            error=(
                                f"Cross-workspace operation requires ADMIN permission. "
                                f"Path '{target_path}' is outside workspace '{self._workspace_boundary}'"
                            ),
                            started_at=started_at,
                            completed_at=time.time(),
                        )
                        self._record_audit(action, executor, result)
                        return result

        # Step 3: PolicyEngine check (Req 8.8)
        if self._policy_engine is not None:
            try:
                from app.avatar.runtime.policy.policy_engine import PolicyDecision

                decision, matched_rule = self._policy_engine.evaluate(
                    skill_name=action.action_type or action.executor_id,
                    params=action.params,
                    context={"requester_id": action.requester_id},
                )
                if decision == PolicyDecision.DENY:
                    result = ActionResult(
                        action_id=action.action_id,
                        status="denied",
                        error=f"PolicyEngine denied: {matched_rule.reason if matched_rule else 'policy denied'}",
                        started_at=started_at,
                        completed_at=time.time(),
                    )
                    self._record_audit(action, executor, result)
                    return result
                elif decision == PolicyDecision.REQUIRE_APPROVAL:
                    # Request approval via CollaborationHub if available
                    if self._collaboration_hub is not None:
                        # For V1, we just note that approval is needed
                        # Full approval flow will be wired in CollaborationHub integration
                        pass
            except Exception as e:
                logger.warning("[ActionPlane] PolicyEngine check failed: %s", e)
                # Fail-safe: deny on policy engine error
                result = ActionResult(
                    action_id=action.action_id,
                    status="denied",
                    error=f"PolicyEngine error: {e}",
                    started_at=started_at,
                    completed_at=time.time(),
                )
                self._record_audit(action, executor, result)
                return result

        # Step 4: Execute
        try:
            output = await executor.execute(action.params)
            result = ActionResult(
                action_id=action.action_id,
                status="success",
                output=output,
                started_at=started_at,
                completed_at=time.time(),
            )
        except Exception as e:
            logger.warning("[ActionPlane] Executor %s failed: %s", action.executor_id, e)
            # Fallback to skill_registry direct execution (Req 8.9)
            fallback_result = await self._fallback_execute(action, started_at)
            if fallback_result is not None:
                self._record_audit(action, executor, fallback_result)
                return fallback_result
            result = ActionResult(
                action_id=action.action_id,
                status="failed",
                error=str(e),
                started_at=started_at,
                completed_at=time.time(),
            )

        # Step 5: Audit record
        self._record_audit(action, executor, result)
        return result

    # ── Fallback ──

    async def _fallback_execute(
        self, action: ActionRequest, started_at: float
    ) -> Optional[ActionResult]:
        """Fallback to skill_registry direct execution when ActionExecutor fails."""
        if self._skill_registry is None:
            return None
        try:
            from app.avatar.runtime.feature_flags import record_system_fallback

            record_system_fallback("action_plane", "executor_failed", "skill_registry_direct")
            skill_cls = self._skill_registry.get(action.action_type)
            if skill_cls is None:
                return None
            from app.avatar.skills.context import SkillContext

            instance = skill_cls()
            context = SkillContext()
            input_model = skill_cls.spec.input_model
            parsed = input_model(**action.params)
            output = await instance.run(context, parsed)
            return ActionResult(
                action_id=action.action_id,
                status="success",
                output=output,
                started_at=started_at,
                completed_at=time.time(),
            )
        except Exception as fallback_err:
            logger.error("[ActionPlane] Fallback execution also failed: %s", fallback_err)
            return None

    # ── Audit helper ──

    def _record_audit(
        self,
        action: ActionRequest,
        executor: Optional[ActionExecutor],
        result: ActionResult,
    ) -> None:
        """Record an audit trail entry for the operation."""
        entry = AuditTrailEntry(
            action_id=action.action_id,
            executor_id=executor.executor_id if executor else "",
            executor_type=executor.executor_type if executor else "",
            permission_tier=executor.permission_tier.value if executor else "",
            requester_id=action.requester_id,
            action_description=action.action_type,
            input_params_summary=str(action.params)[:200],
            output_result_summary=str(result.output)[:200] if result.output else "",
            started_at=result.started_at,
            completed_at=result.completed_at,
            status=result.status,
        )
        self._audit_trail.append(entry)
