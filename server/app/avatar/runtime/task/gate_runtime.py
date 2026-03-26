"""GateRuntime — persistent human-in-the-loop gate lifecycle.

Replaces the in-memory suspend/resume pattern with a durable state machine:
  1. ClarificationEngine/ApprovalCheck detects need → create_gate()
  2. Session transitions to WAITING_INPUT, current execution round ends
  3. EventBus emits gate_triggered for frontend notification
  4. User submits answers via API → submit_response()
  5. Answers merged into TaskDefinition/PlanInputs → merge_answers()
  6. Session transitions to RESUMING → execution resumes

All gate types (clarification / approval / confirmation / missing_input)
share this single runtime. Frontend presentation (chat bubble, modal,
form) is a UI concern, not a backend concern.

All tunable parameters in GateRuntimeConfig.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GateRuntimeConfig:
    """Tunable parameters for GateRuntime."""
    # Max time (seconds) a gate can stay active before auto-expiring
    gate_timeout_seconds: float = 1800.0  # 30 minutes
    # Max blocking questions to include per gate
    max_blocking_questions: int = 5
    # Batch assumption display threshold
    batch_assumption_threshold: int = 5
    # Whether to auto-expire gates on timeout (vs keep waiting)
    auto_expire_enabled: bool = True


@dataclass
class GateContext:
    """Structured context for a gate request, independent of DB model."""
    gate_id: str
    gate_type: str  # clarification / approval / confirmation / missing_input
    trigger_reason: str
    blocking_questions: List[Dict[str, Any]] = field(default_factory=list)
    required_info: Dict[str, Any] = field(default_factory=dict)
    pending_assumptions: List[Dict[str, Any]] = field(default_factory=list)
    version: int = 1


@dataclass
class GateResponse:
    """Structured response from user."""
    gate_id: str
    version: int
    answers: Dict[str, Any] = field(default_factory=dict)
    approved: Optional[bool] = None  # For approval gates


@dataclass
class GateMergeResult:
    """Result of merging gate answers back into execution context."""
    success: bool
    merge_target: str = ""  # task_definition / env_context / plan_inputs
    still_blocked: bool = False  # True if re-assessment still shows blocked
    updated_questions: List[Dict[str, Any]] = field(default_factory=list)
    reason: str = ""


class GateRuntime:
    """Persistent gate lifecycle manager.

    Coordinates between:
    - ClarificationEngine / ApprovalCheck (gate creators)
    - DB persistence (GateRequestRecord)
    - EventBus (notification)
    - TaskDefinition / PlanInputs (answer merge targets)
    - Session state machine (WAITING_INPUT transitions)
    """

    def __init__(
        self,
        config: Optional[GateRuntimeConfig] = None,
        event_bus: Optional[Any] = None,
    ) -> None:
        self._cfg = config or GateRuntimeConfig()
        self._event_bus = event_bus

    # ------------------------------------------------------------------
    # Gate creation
    # ------------------------------------------------------------------

    def create_gate(
        self,
        task_session_id: str,
        session_id: str,
        gate_type: str,
        trigger_reason: str,
        blocking_questions: Optional[List[Dict[str, Any]]] = None,
        required_info: Optional[Dict[str, Any]] = None,
        pending_assumptions: Optional[List[Dict[str, Any]]] = None,
    ) -> GateContext:
        """Create and persist a new gate request.

        Returns GateContext for the caller to use (e.g. to build
        the WAITING_INPUT exit signal).
        """
        gate_id = str(uuid.uuid4())
        questions = (blocking_questions or [])[:self._cfg.max_blocking_questions]

        # Persist to DB
        try:
            from app.db.long_task_models import GateRequestRecord
            from app.db.database import get_session

            record = GateRequestRecord(
                id=gate_id,
                task_session_id=task_session_id,
                session_id=session_id,
                gate_type=gate_type,
                status="active",
                version=1,
                trigger_reason=trigger_reason,
                blocking_questions_json=(
                    json.dumps(questions, ensure_ascii=False) if questions else None
                ),
                required_info_json=(
                    json.dumps(required_info, ensure_ascii=False) if required_info else None
                ),
                pending_assumptions_json=(
                    json.dumps(pending_assumptions, ensure_ascii=False)
                    if pending_assumptions else None
                ),
            )
            with get_session() as db:
                db.add(record)
                db.commit()
            logger.info(
                "[GateRuntime] Created gate %s: type=%s reason=%s questions=%d",
                gate_id, gate_type, trigger_reason, len(questions),
            )
        except Exception as exc:
            logger.warning(
                "[GateRuntime] DB persist failed (gate still usable in-memory): %s", exc,
            )

        # Emit event for frontend notification
        self._emit_gate_event("gate_triggered", {
            "gate_id": gate_id,
            "task_session_id": task_session_id,
            "session_id": session_id,
            "gate_type": gate_type,
            "trigger_reason": trigger_reason,
            "blocking_questions": questions,
            "required_info": required_info or {},
            "pending_assumptions": pending_assumptions or [],
        })

        return GateContext(
            gate_id=gate_id,
            gate_type=gate_type,
            trigger_reason=trigger_reason,
            blocking_questions=questions,
            required_info=required_info or {},
            pending_assumptions=pending_assumptions or [],
        )

    # ------------------------------------------------------------------
    # Response submission (called from API endpoint)
    # ------------------------------------------------------------------

    def submit_response(self, gate_response: GateResponse) -> bool:
        """Submit user response to an active gate.

        Returns True if accepted, False if gate is no longer active
        or version mismatch (idempotency guard).
        """
        try:
            from app.db.long_task_models import GateRequestRecord
            from app.db.database import get_session

            with get_session() as db:
                record = db.get(GateRequestRecord, gate_response.gate_id)
                if record is None:
                    logger.warning(
                        "[GateRuntime] Gate %s not found", gate_response.gate_id,
                    )
                    return False

                if record.status != "active":
                    logger.info(
                        "[GateRuntime] Gate %s already %s, rejecting response",
                        gate_response.gate_id, record.status,
                    )
                    return False

                if record.version != gate_response.version:
                    logger.info(
                        "[GateRuntime] Gate %s version mismatch: expected %d got %d",
                        gate_response.gate_id, record.version, gate_response.version,
                    )
                    return False

                # Accept the response
                record.status = "answered"
                record.answers_json = json.dumps(
                    gate_response.answers, ensure_ascii=False,
                )
                record.answered_at = datetime.now(timezone.utc)
                record.updated_at = datetime.now(timezone.utc)
                _gate_type = record.gate_type  # capture before session closes
                db.add(record)
                db.commit()

            logger.info(
                "[GateRuntime] Gate %s answered", gate_response.gate_id,
            )

            self._emit_gate_event("gate_answered", {
                "gate_id": gate_response.gate_id,
                "gate_type": _gate_type,
                "has_answers": bool(gate_response.answers),
                "approved": gate_response.approved,
            })
            return True

        except Exception as exc:
            logger.error("[GateRuntime] submit_response failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Answer merge (maps answers back to structured fields)
    # ------------------------------------------------------------------

    def merge_answers(
        self,
        gate_id: str,
        task_def: Optional[Any] = None,
        env_context: Optional[Dict[str, Any]] = None,
        clarification_engine: Optional[Any] = None,
    ) -> GateMergeResult:
        """Merge gate answers into TaskDefinition or env_context.

        Steps:
        1. Load gate record + answers from DB
        2. Map answers to TaskDefinition fields (if clarification)
        3. Re-assess via ClarificationEngine
        4. If still blocked → update gate version, return still_blocked=True
        5. If ready → mark gate as merged, return success
        """
        try:
            from app.db.long_task_models import GateRequestRecord
            from app.db.database import get_session

            with get_session() as db:
                record = db.get(GateRequestRecord, gate_id)
                if record is None or record.status != "answered":
                    return GateMergeResult(
                        success=False,
                        reason=f"gate {gate_id} not in answered state",
                    )

                answers = json.loads(record.answers_json or "{}")
                gate_type = record.gate_type

            # Route by gate type
            if gate_type == "approval":
                return self._merge_approval(gate_id, answers, env_context)

            if gate_type in ("clarification", "missing_input"):
                return self._merge_clarification(
                    gate_id, answers, task_def, env_context, clarification_engine,
                )

            if gate_type == "confirmation":
                return self._merge_confirmation(gate_id, answers, env_context)

            return GateMergeResult(
                success=False, reason=f"unknown gate_type: {gate_type}",
            )

        except Exception as exc:
            logger.error("[GateRuntime] merge_answers failed: %s", exc)
            return GateMergeResult(success=False, reason=str(exc))

    def _merge_approval(
        self,
        gate_id: str,
        answers: Dict[str, Any],
        env_context: Optional[Dict[str, Any]],
    ) -> GateMergeResult:
        """Merge approval gate response."""
        approved = answers.get("approved", False)
        if env_context is not None:
            env_context["_approval_granted"] = approved
        self._mark_merged(gate_id, "env_context")
        return GateMergeResult(
            success=True,
            merge_target="env_context",
            reason="approved" if approved else "rejected",
        )

    def _merge_clarification(
        self,
        gate_id: str,
        answers: Dict[str, Any],
        task_def: Optional[Any],
        env_context: Optional[Dict[str, Any]],
        clarification_engine: Optional[Any],
    ) -> GateMergeResult:
        """Merge clarification answers into TaskDefinition fields.

        Maps answer keys to TaskDefinition field paths:
        - "objective" → task_def.objective.text
        - "deliverable_N" → task_def.deliverables[N]
        - "constraint_N" → task_def.constraints[N]
        - Generic keys → env_context["clarification_answers"]
        """
        if env_context is not None:
            env_context["clarification_answers"] = answers

        if task_def is not None:
            for key, value in answers.items():
                if key == "objective" and hasattr(task_def, "objective"):
                    task_def.objective.text = str(value)
                    task_def.objective.source = "extracted"
                elif key.startswith("deliverable_"):
                    # Future: map to specific deliverable index
                    pass
                # Open questions answered → remove from list
                oq = getattr(task_def, "open_questions", None)
                if oq and isinstance(oq, list):
                    task_def.open_questions = [
                        q for q in oq if q.lower() not in str(value).lower()
                    ]

        # Re-assess if ClarificationEngine available
        still_blocked = False
        updated_questions: List[Dict[str, Any]] = []
        if clarification_engine is not None and task_def is not None:
            try:
                readiness = clarification_engine.assess(task_def)
                if readiness.status == "blocked":
                    still_blocked = True
                    updated_questions = [
                        {"question": q.question, "priority": q.priority.value}
                        for q in readiness.blocking_questions
                    ]
                    # Bump gate version for follow-up
                    self._bump_version(gate_id, updated_questions)
            except Exception as exc:
                logger.warning("[GateRuntime] Re-assessment failed: %s", exc)

        if not still_blocked:
            self._mark_merged(gate_id, "task_definition")

        return GateMergeResult(
            success=not still_blocked,
            merge_target="task_definition",
            still_blocked=still_blocked,
            updated_questions=updated_questions,
            reason="still_blocked" if still_blocked else "merged",
        )

    def _merge_confirmation(
        self,
        gate_id: str,
        answers: Dict[str, Any],
        env_context: Optional[Dict[str, Any]],
    ) -> GateMergeResult:
        """Merge confirmation gate response."""
        confirmed = answers.get("confirmed", False)
        if env_context is not None:
            env_context["_confirmation_granted"] = confirmed
        self._mark_merged(gate_id, "env_context")
        return GateMergeResult(
            success=True,
            merge_target="env_context",
            reason="confirmed" if confirmed else "declined",
        )

    # ------------------------------------------------------------------
    # Gate lifecycle helpers
    # ------------------------------------------------------------------

    def _mark_merged(self, gate_id: str, merge_target: str) -> None:
        """Transition gate to merged status."""
        try:
            from app.db.long_task_models import GateRequestRecord
            from app.db.database import get_session

            with get_session() as db:
                record = db.get(GateRequestRecord, gate_id)
                if record:
                    record.status = "merged"
                    record.merge_target = merge_target
                    record.merged_at = datetime.now(timezone.utc)
                    record.updated_at = datetime.now(timezone.utc)
                    db.add(record)
                    db.commit()
        except Exception as exc:
            logger.warning("[GateRuntime] _mark_merged failed: %s", exc)

    def _bump_version(
        self, gate_id: str, updated_questions: List[Dict[str, Any]],
    ) -> None:
        """Bump gate version and update questions for follow-up round."""
        try:
            from app.db.long_task_models import GateRequestRecord
            from app.db.database import get_session

            with get_session() as db:
                record = db.get(GateRequestRecord, gate_id)
                if record:
                    record.version += 1
                    record.status = "active"
                    record.blocking_questions_json = json.dumps(
                        updated_questions, ensure_ascii=False,
                    )
                    record.answers_json = None
                    record.answered_at = None
                    record.updated_at = datetime.now(timezone.utc)
                    db.add(record)
                    db.commit()

            self._emit_gate_event("gate_updated", {
                "gate_id": gate_id,
                "new_version": record.version if record else 0,
                "updated_questions": updated_questions,
            })
        except Exception as exc:
            logger.warning("[GateRuntime] _bump_version failed: %s", exc)

    def expire_stale_gates(self, task_session_id: str) -> int:
        """Expire gates that have exceeded timeout. Returns count expired."""
        if not self._cfg.auto_expire_enabled:
            return 0

        try:
            from app.db.long_task_models import GateRequestRecord
            from app.db.database import get_session

            expired_count = 0
            cutoff = time.time() - self._cfg.gate_timeout_seconds

            with get_session() as db:
                from sqlmodel import select
                stmt = select(GateRequestRecord).where(
                    GateRequestRecord.task_session_id == task_session_id,
                    GateRequestRecord.status == "active",
                )
                records = db.exec(stmt).all()
                for record in records:
                    if record.created_at.timestamp() < cutoff:
                        record.status = "expired"
                        record.updated_at = datetime.now(timezone.utc)
                        db.add(record)
                        expired_count += 1
                if expired_count:
                    db.commit()

            if expired_count:
                self._emit_gate_event("gate_expired", {
                    "task_session_id": task_session_id,
                    "expired_count": expired_count,
                })
            return expired_count

        except Exception as exc:
            logger.warning("[GateRuntime] expire_stale_gates failed: %s", exc)
            return 0

    def get_active_gate(self, task_session_id: str) -> Optional[GateContext]:
        """Load the current active gate for a session (if any)."""
        try:
            from app.db.long_task_models import GateRequestRecord
            from app.db.database import get_session

            with get_session() as db:
                from sqlmodel import select
                stmt = (
                    select(GateRequestRecord)
                    .where(
                        GateRequestRecord.task_session_id == task_session_id,
                        GateRequestRecord.status == "active",
                    )
                    .order_by(GateRequestRecord.created_at.desc())  # type: ignore
                )
                record = db.exec(stmt).first()
                if record is None:
                    return None

                return GateContext(
                    gate_id=record.id,
                    gate_type=record.gate_type,
                    trigger_reason=record.trigger_reason,
                    blocking_questions=json.loads(
                        record.blocking_questions_json or "[]",
                    ),
                    required_info=json.loads(record.required_info_json or "{}"),
                    pending_assumptions=json.loads(
                        record.pending_assumptions_json or "[]",
                    ),
                    version=record.version,
                )
        except Exception as exc:
            logger.warning("[GateRuntime] get_active_gate failed: %s", exc)
            return None

    def cancel_gate(self, gate_id: str) -> bool:
        """Cancel an active gate (e.g. when task is cancelled)."""
        try:
            from app.db.long_task_models import GateRequestRecord
            from app.db.database import get_session

            with get_session() as db:
                record = db.get(GateRequestRecord, gate_id)
                if record and record.status == "active":
                    record.status = "cancelled"
                    record.updated_at = datetime.now(timezone.utc)
                    db.add(record)
                    db.commit()
                    return True
            return False
        except Exception as exc:
            logger.warning("[GateRuntime] cancel_gate failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Event emission
    # ------------------------------------------------------------------

    def _emit_gate_event(self, event_type_name: str, payload: Dict[str, Any]) -> None:
        """Emit gate event via EventBus for frontend notification."""
        if self._event_bus is None:
            return
        try:
            from app.avatar.runtime.events.types import Event, EventType
            _type_map = {
                "gate_triggered": EventType.GATE_TRIGGERED,
                "gate_answered": EventType.GATE_ANSWERED,
                "gate_expired": EventType.GATE_EXPIRED,
                "gate_resumed": EventType.GATE_RESUMED,
            }
            _etype = _type_map.get(event_type_name, EventType.GATE_TRIGGERED)
            event = Event(
                type=_etype,
                source="gate_runtime",
                payload={"gate_event": event_type_name, **payload},
            )
            self._event_bus.publish(event)
        except Exception as exc:
            logger.debug("[GateRuntime] Event emission failed: %s", exc)
