"""CollaborationHub — upgraded from CollaborationGate.

Unified management of all collaboration interaction types:
approval_request, clarification_request, status_update, risk_report,
deliverable_handoff, feedback_request, follow_up_reminder.

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from ..feature_flags import record_system_fallback

logger = logging.getLogger(__name__)

# Auto-generate StatusUpdate thresholds
_BLOCKED_TIMEOUT_S = 10 * 60  # 10 minutes


# ---------------------------------------------------------------------------
# InteractionType enum
# ---------------------------------------------------------------------------

class InteractionType(str, Enum):
    APPROVAL_REQUEST = "approval_request"
    CLARIFICATION_REQUEST = "clarification_request"
    STATUS_UPDATE = "status_update"
    RISK_REPORT = "risk_report"
    DELIVERABLE_HANDOFF = "deliverable_handoff"
    FEEDBACK_REQUEST = "feedback_request"
    FOLLOW_UP_REMINDER = "follow_up_reminder"


# ---------------------------------------------------------------------------
# Interaction dataclass
# ---------------------------------------------------------------------------

@dataclass
class Interaction:
    """A single collaboration interaction with lifecycle tracking."""
    interaction_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    interaction_type: InteractionType = InteractionType.STATUS_UPDATE
    content: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    response: Optional[Dict[str, Any]] = None
    response_time: Optional[float] = None
    status: str = "pending"  # pending / responded / timeout / cancelled
    correlation_id: Optional[str] = None
    schema_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "interaction_id": self.interaction_id,
            "interaction_type": self.interaction_type.value,
            "content": dict(self.content),
            "created_at": self.created_at,
            "response": self.response,
            "response_time": self.response_time,
            "status": self.status,
            "correlation_id": self.correlation_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Interaction:
        return cls(
            interaction_id=data.get("interaction_id", str(uuid.uuid4())),
            interaction_type=InteractionType(data["interaction_type"]) if "interaction_type" in data else InteractionType.STATUS_UPDATE,
            content=dict(data.get("content") or {}),
            created_at=data.get("created_at", time.time()),
            response=data.get("response"),
            response_time=data.get("response_time"),
            status=data.get("status", "pending"),
            correlation_id=data.get("correlation_id"),
            schema_version=data.get("schema_version", "1.0.0"),
        )


# ---------------------------------------------------------------------------
# StatusUpdate dataclass
# ---------------------------------------------------------------------------

@dataclass
class StatusUpdate:
    """Agent-generated work progress report."""
    update_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    summary: str = ""
    completed_items: List[str] = field(default_factory=list)
    current_blockers: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)
    estimated_completion: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    schema_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "update_id": self.update_id,
            "task_id": self.task_id,
            "summary": self.summary,
            "completed_items": list(self.completed_items),
            "current_blockers": list(self.current_blockers),
            "next_steps": list(self.next_steps),
            "estimated_completion": self.estimated_completion,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> StatusUpdate:
        return cls(
            update_id=data.get("update_id", str(uuid.uuid4())),
            task_id=data.get("task_id", ""),
            summary=data.get("summary", ""),
            completed_items=list(data.get("completed_items") or []),
            current_blockers=list(data.get("current_blockers") or []),
            next_steps=list(data.get("next_steps") or []),
            estimated_completion=data.get("estimated_completion"),
            created_at=data.get("created_at", time.time()),
            schema_version=data.get("schema_version", "1.0.0"),
        )


# ---------------------------------------------------------------------------
# CollaborationHub
# ---------------------------------------------------------------------------

# Try to import CollaborationGate for inheritance; standalone if unavailable
try:
    from ..task.collaboration_gate import CollaborationGate as _BaseGate

    class _HubBase(_BaseGate):
        pass
except Exception:
    class _HubBase:  # type: ignore[no-redef]
        """Standalone base when CollaborationGate is not available."""
        def __init__(self, timeout: float = 1800) -> None:
            self._timeout = timeout


class CollaborationHub(_HubBase):
    """Upgraded from CollaborationGate.

    Unified management of all collaboration interactions.
    Falls back to CollaborationGate on exception.

    Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7
    """

    def __init__(
        self,
        timeout: float = 1800,
        user_memory: Any = None,
        task_event_stream: Any = None,
        audit_trail: Any = None,
    ) -> None:
        super().__init__(timeout=timeout)
        self._interactions: Dict[str, Interaction] = {}
        self._user_memory = user_memory
        self._task_event_stream = task_event_stream
        self._audit_trail = audit_trail

    # ------------------------------------------------------------------
    # Core interaction management
    # ------------------------------------------------------------------

    def create_interaction(self, interaction: Interaction) -> str:
        """Create and store a new interaction. Returns interaction_id."""
        self._interactions[interaction.interaction_id] = interaction
        # Push to TaskEventStream if available
        self._push_to_event_stream(
            "collaboration.interaction_created",
            interaction.to_dict(),
        )
        # Record to AuditTrail
        self._record_audit(interaction, "created")
        return interaction.interaction_id

    def respond(
        self,
        interaction_id: str,
        response: Dict[str, Any],
    ) -> None:
        """Record a response to a pending interaction."""
        interaction = self._interactions.get(interaction_id)
        if interaction is None:
            logger.warning("[CollaborationHub] interaction %s not found", interaction_id)
            return
        interaction.response = response
        interaction.response_time = time.time()
        interaction.status = "responded"
        # Feedback loop: record to UserMemory.approval_patterns
        self._record_feedback(interaction, response)
        # Push update to frontend
        self._push_to_event_stream(
            "collaboration.interaction_responded",
            interaction.to_dict(),
        )
        self._record_audit(interaction, "responded")

    def get_interaction(self, interaction_id: str) -> Optional[Interaction]:
        """Get an interaction by ID."""
        return self._interactions.get(interaction_id)

    def list_pending(self) -> List[Interaction]:
        """List all pending interactions."""
        return [
            i for i in self._interactions.values()
            if i.status == "pending"
        ]

    # ------------------------------------------------------------------
    # StatusUpdate auto-generation
    # ------------------------------------------------------------------

    def generate_status_update(
        self,
        task_id: str,
        summary: str,
        completed_items: Optional[List[str]] = None,
        current_blockers: Optional[List[str]] = None,
        next_steps: Optional[List[str]] = None,
        estimated_completion: Optional[float] = None,
    ) -> StatusUpdate:
        """Auto-generate a StatusUpdate and create an interaction for it.

        Triggers: PhasePlan complete / blocked > 10 min / risk signal / user request.
        Requirements: 7.3
        """
        update = StatusUpdate(
            task_id=task_id,
            summary=summary,
            completed_items=completed_items or [],
            current_blockers=current_blockers or [],
            next_steps=next_steps or [],
            estimated_completion=estimated_completion,
        )
        interaction = Interaction(
            interaction_type=InteractionType.STATUS_UPDATE,
            content=update.to_dict(),
        )
        self.create_interaction(interaction)
        return update

    # ------------------------------------------------------------------
    # Convenience methods for RuntimeKernel integration
    # ------------------------------------------------------------------

    def notify_status(self, decision: Any) -> None:
        """Called by RuntimeKernel._apply_emit_status."""
        reason = getattr(decision, "reason", "status update")
        task_id = getattr(decision, "target_task_id", "") or ""
        self.generate_status_update(task_id=task_id, summary=reason)

    def request_approval(self, decision: Any) -> None:
        """Called by RuntimeKernel._apply_require_approval."""
        interaction = Interaction(
            interaction_type=InteractionType.APPROVAL_REQUEST,
            content={
                "reason": getattr(decision, "reason", ""),
                "target_task_id": getattr(decision, "target_task_id", ""),
                "metadata": getattr(decision, "metadata", {}),
            },
            correlation_id=getattr(decision, "target_task_id", None),
        )
        self.create_interaction(interaction)

    def escalate(self, decision: Any) -> None:
        """Called by RuntimeKernel._apply_escalate."""
        interaction = Interaction(
            interaction_type=InteractionType.RISK_REPORT,
            content={
                "reason": getattr(decision, "reason", "escalated"),
                "target_task_id": getattr(decision, "target_task_id", ""),
                "metadata": getattr(decision, "metadata", {}),
            },
            correlation_id=getattr(decision, "target_task_id", None),
        )
        self.create_interaction(interaction)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_feedback(self, interaction: Interaction, response: Dict[str, Any]) -> None:
        """Record user feedback to UserMemory.approval_patterns."""
        if self._user_memory is None:
            return
        try:
            patterns = getattr(self._user_memory, "approval_patterns", {})
            itype = interaction.interaction_type.value
            action = response.get("action", response.get("approved", "unknown"))
            patterns[itype] = str(action)
        except Exception as exc:
            logger.debug("[CollaborationHub] feedback recording error: %s", exc)

    def _push_to_event_stream(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Push interaction events to TaskEventStream for frontend display."""
        if self._task_event_stream is None:
            return
        try:
            self._task_event_stream.emit(event_type, payload)
        except Exception as exc:
            logger.debug("[CollaborationHub] event stream push error: %s", exc)

    def _record_audit(self, interaction: Interaction, action: str) -> None:
        """Record interaction to AuditTrail."""
        if self._audit_trail is None:
            return
        try:
            from ..action_plane.audit_trail import AuditTrailEntry
            entry = AuditTrailEntry(
                action_id=interaction.interaction_id,
                executor_id="collaboration_hub",
                executor_type="collaboration",
                action_description=f"{interaction.interaction_type.value}:{action}",
                status=interaction.status,
            )
            self._audit_trail.append(entry)
        except Exception as exc:
            logger.debug("[CollaborationHub] audit recording error: %s", exc)

    # ------------------------------------------------------------------
    # HandoffEnvelope management (Multi-Agent extension)
    # Requirements: 9.4, 9.5, 9.6, 9.7, 23.1, 23.2, 23.3, 23.4
    # ------------------------------------------------------------------

    def validate_and_deliver(
        self,
        envelope: Any,
        registry: Any = None,
    ) -> tuple:
        """校验 HandoffEnvelope 载荷并投递.

        1. 根据 target_role 的 RoleSpec.input_schema 校验 payload
        2. Schema 前置校验不通过时直接拒绝，不进入执行流程
        3. 校验通过记录到 HandoffHistory，发出 handoff.created AgentEvent
        Returns (success: bool, message: str).
        """
        if not hasattr(self, "_handoff_history"):
            self._handoff_history: List[Any] = []

        target_role = getattr(envelope, "target_role", "")
        payload = getattr(envelope, "payload", {})

        # Schema validation
        if registry is not None and target_role:
            spec = registry.get(target_role) if hasattr(registry, "get") else None
            if spec is not None:
                input_schema = getattr(spec, "input_schema", {})
                if input_schema and input_schema.get("type") == "object":
                    required = input_schema.get("required", [])
                    for req_field in required:
                        if req_field not in payload:
                            if hasattr(envelope, "status"):
                                envelope.status = "rejected"
                            return (False, f"Missing required field: {req_field}")

        # Deliver
        if hasattr(envelope, "status"):
            envelope.status = "delivered"
        self._handoff_history.append(envelope)

        # Emit event
        self._push_to_event_stream("handoff.created", {
            "envelope_id": getattr(envelope, "envelope_id", ""),
            "source_role": getattr(envelope, "source_role", ""),
            "target_role": target_role,
            "task_id": getattr(envelope, "task_id", ""),
        })

        return (True, "delivered")

    def mark_received(self, envelope_id: str) -> None:
        """标记信封已被目标角色接收，发出 handoff.received 事件."""
        if not hasattr(self, "_handoff_history"):
            return
        for env in self._handoff_history:
            if getattr(env, "envelope_id", "") == envelope_id:
                env.status = "received"
                self._push_to_event_stream("handoff.received", {
                    "envelope_id": envelope_id,
                })
                return

    def mark_completed(self, envelope_id: str) -> None:
        """标记信封处理完成，发出 handoff.completed 事件."""
        if not hasattr(self, "_handoff_history"):
            return
        for env in self._handoff_history:
            if getattr(env, "envelope_id", "") == envelope_id:
                env.status = "completed"
                self._push_to_event_stream("handoff.completed", {
                    "envelope_id": envelope_id,
                })
                return

    def query_history(
        self,
        source_role: Optional[str] = None,
        target_role: Optional[str] = None,
        time_range: Optional[tuple] = None,
    ) -> List[Any]:
        """按条件查询交接历史."""
        if not hasattr(self, "_handoff_history"):
            return []
        results = []
        for env in self._handoff_history:
            if source_role is not None and getattr(env, "source_role", "") != source_role:
                continue
            if target_role is not None and getattr(env, "target_role", "") != target_role:
                continue
            if time_range is not None:
                created_at = getattr(env, "created_at", 0)
                if created_at < time_range[0] or created_at > time_range[1]:
                    continue
            results.append(env)
        return results
