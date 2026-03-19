"""
CollaborationGate — human-in-the-loop approval and clarification.

Implements suspend/resume protocol, priority ordering (Approval > Clarification),
deduplication, timeout, and batch assumption display.
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Timeout defaults (seconds)
DEFAULT_GATE_TIMEOUT = 1800  # 30 minutes
# Batch assumption threshold
BATCH_ASSUMPTION_THRESHOLD = 5


class GateType(str, Enum):
    """Type of collaboration gate."""
    APPROVAL = "approval"
    CLARIFICATION = "clarification"


@dataclass
class GateRequest:
    """Serializable request for human collaboration.

    Sent via TaskEventStream when execution needs human input.
    """
    gate_type: GateType
    trigger_reason: str
    required_info: Dict[str, Any] = field(default_factory=dict)
    pending_assumptions: List[Dict] = field(default_factory=list)  # batch display mode
    timestamp: float = 0.0
    schema_version: str = "1.0.0"


def _question_signature(related_field: str, question_text: str, gate_type: GateType) -> str:
    """Deterministic dedup key: hash of (related_field + normalized_question + gate_type)."""
    normalized = question_text.strip().lower()
    raw = f"{related_field}|{normalized}|{gate_type.value}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class CollaborationGate:
    """Human-in-the-loop gate for approval and clarification.

    Priority: ApprovalGate > ClarificationGate.
    Dedup: ClarificationGate uses question_signature; ApprovalGate is per-node.
    """

    def __init__(self, timeout: float = DEFAULT_GATE_TIMEOUT):
        self._timeout = timeout
        self._pending_signatures: Set[str] = set()
        self._suspended_state: Optional[Dict[str, Any]] = None
        self._pending_gate: Optional[GateRequest] = None

    # ------------------------------------------------------------------
    # Suspend / Resume
    # ------------------------------------------------------------------

    async def suspend(
        self,
        gate_request: GateRequest,
        env_context: Dict[str, Any],
    ) -> None:
        """Suspend execution and emit gate request.

        Steps:
        1. Save execution state reference
        2. Serialize GateRequest
        3. Mark as waiting_for_human
        """
        gate_request.timestamp = time.time()
        self._suspended_state = {
            "env_context_snapshot": dict(env_context),
            "suspended_at": gate_request.timestamp,
        }
        self._pending_gate = gate_request
        logger.info(
            "Execution suspended: gate_type=%s reason=%s",
            gate_request.gate_type.value,
            gate_request.trigger_reason,
        )

    async def resume(
        self,
        user_response: Dict[str, Any],
        env_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Resume execution after user response.

        Returns dict with resume action:
        - {"action": "continue", ...} for approved/clarified
        - {"action": "skip", ...} for rejected approval
        """
        if self._pending_gate is None:
            return {"action": "continue", "reason": "no_pending_gate"}

        gate = self._pending_gate
        self._pending_gate = None
        self._suspended_state = None

        if gate.gate_type == GateType.APPROVAL:
            approved = user_response.get("approved", False)
            if not approved:
                return {"action": "skip", "reason": "approval_rejected"}
            return {"action": "continue", "reason": "approved"}

        if gate.gate_type == GateType.CLARIFICATION:
            # Inject user answers into env_context
            answers = user_response.get("answers", {})
            env_context["clarification_answers"] = answers
            # Clear dedup signatures for answered questions
            for sig in list(self._pending_signatures):
                self._pending_signatures.discard(sig)
            return {"action": "continue", "reason": "clarified", "answers": answers}

        return {"action": "continue", "reason": "unknown_gate_type"}

    # ------------------------------------------------------------------
    # Check methods
    # ------------------------------------------------------------------

    def check_approval_needed(
        self,
        node: Any,
        task_def: Any,
    ) -> Optional[GateRequest]:
        """Check if a node requires approval before execution.

        Triggers when:
        - Node is associated with a high-severity risk in TaskDefinition
        - Node metadata contains requires_approval flag
        """
        # Check node metadata
        metadata = getattr(node, "metadata", {}) or {}
        if metadata.get("requires_approval"):
            return GateRequest(
                gate_type=GateType.APPROVAL,
                trigger_reason=f"Node {getattr(node, 'id', '?')} requires approval",
                required_info={
                    "node_id": getattr(node, "id", ""),
                    "capability": getattr(node, "capability_name", ""),
                },
            )

        # Check task_def risks
        risks = getattr(task_def, "risks", []) or []
        node_cap = getattr(node, "capability_name", "")
        for risk in risks:
            severity = getattr(risk, "severity", "medium")
            if severity == "high":
                return GateRequest(
                    gate_type=GateType.APPROVAL,
                    trigger_reason=f"High-risk operation: {getattr(risk, 'text', '')}",
                    required_info={
                        "node_id": getattr(node, "id", ""),
                        "risk_description": getattr(risk, "description", ""),
                    },
                )

        return None

    def check_clarification_needed(
        self,
        patch: Any,
        task_def: Any,
    ) -> Optional[GateRequest]:
        """Check if a planner patch needs clarification.

        Triggers when open_questions exist and haven't been asked yet (dedup).
        """
        open_questions = getattr(task_def, "open_questions", []) or []
        if not open_questions:
            return None

        new_questions = []
        for q in open_questions:
            sig = _question_signature("", q, GateType.CLARIFICATION)
            if sig not in self._pending_signatures:
                new_questions.append(q)
                self._pending_signatures.add(sig)

        if not new_questions:
            return None

        # Check batch assumption display
        assumptions = getattr(task_def, "assumptions", []) or []
        pending_assumptions = []
        if len(assumptions) > BATCH_ASSUMPTION_THRESHOLD:
            pending_assumptions = [
                {"text": getattr(a, "text", str(a)),
                 "confidence": getattr(a, "confidence_level", "medium")}
                for a in assumptions
            ]

        return GateRequest(
            gate_type=GateType.CLARIFICATION,
            trigger_reason="open_questions_detected",
            required_info={"questions": new_questions},
            pending_assumptions=pending_assumptions,
        )

    # ------------------------------------------------------------------
    # Priority resolution
    # ------------------------------------------------------------------

    def resolve_priority(
        self,
        approval_gate: Optional[GateRequest],
        clarification_gate: Optional[GateRequest],
    ) -> Optional[GateRequest]:
        """ApprovalGate always takes priority over ClarificationGate."""
        if approval_gate is not None:
            return approval_gate
        return clarification_gate

    # ------------------------------------------------------------------
    # Timeout handling
    # ------------------------------------------------------------------

    def check_timeout(self) -> Optional[Dict[str, Any]]:
        """Check if the pending gate has timed out.

        Returns timeout action or None if not timed out.
        """
        if self._suspended_state is None or self._pending_gate is None:
            return None

        elapsed = time.time() - self._suspended_state["suspended_at"]
        if elapsed < self._timeout:
            return None

        gate = self._pending_gate
        self._pending_gate = None
        self._suspended_state = None

        if gate.gate_type == GateType.APPROVAL:
            return {"action": "cancel", "reason": "approval_timeout"}
        if gate.gate_type == GateType.CLARIFICATION:
            return {"action": "continue_with_assumptions", "reason": "clarification_timeout"}
        return {"action": "cancel", "reason": "unknown_timeout"}

    @property
    def is_suspended(self) -> bool:
        return self._pending_gate is not None
