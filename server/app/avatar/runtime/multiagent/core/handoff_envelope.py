"""HandoffEnvelope — 结构化交接信封.

Requirements: 9.1, 9.3
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


HANDOFF_STATUSES = (
    "created", "validated", "delivered", "received",
    "completed", "rejected", "cancelled", "expired",
)


@dataclass
class HandoffEnvelope:
    """Structured handoff between agent roles.

    Produced by a completing subtask, consumed by the next downstream
    subtask's RoleRunner. Carries structured payload references instead
    of raw data — downstream reads only the handoff, not full history.
    """
    envelope_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_role: str = ""
    source_instance_id: str = ""
    target_role: str = ""
    target_instance_id: str = ""
    task_id: str = ""
    # Structured payload: artifact refs, data summaries, open questions
    payload: Dict[str, Any] = field(default_factory=dict)
    artifact_refs: list = field(default_factory=list)  # list of file paths / artifact IDs
    context_summary: str = ""
    acceptance_checklist: list = field(default_factory=list)  # criteria the source claims to have met
    confidence: float = 1.0  # source's self-assessed confidence (0-1)
    open_questions: list = field(default_factory=list)  # unresolved items for downstream
    created_at: float = field(default_factory=time.time)
    status: str = "created"
    schema_version: str = "1.0.0"
    # Worker-initiated feedback from the source node
    feedback: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "envelope_id": self.envelope_id,
            "source_role": self.source_role,
            "source_instance_id": self.source_instance_id,
            "target_role": self.target_role,
            "target_instance_id": self.target_instance_id,
            "task_id": self.task_id,
            "payload": dict(self.payload),
            "artifact_refs": list(self.artifact_refs),
            "context_summary": self.context_summary,
            "acceptance_checklist": list(self.acceptance_checklist),
            "confidence": self.confidence,
            "open_questions": list(self.open_questions),
            "created_at": self.created_at,
            "status": self.status,
            "schema_version": self.schema_version,
            "feedback": dict(self.feedback) if self.feedback else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> HandoffEnvelope:
        return cls(
            envelope_id=data.get("envelope_id", str(uuid.uuid4())),
            source_role=data.get("source_role", ""),
            source_instance_id=data.get("source_instance_id", ""),
            target_role=data.get("target_role", ""),
            target_instance_id=data.get("target_instance_id", ""),
            task_id=data.get("task_id", ""),
            payload=dict(data.get("payload") or {}),
            artifact_refs=list(data.get("artifact_refs") or []),
            context_summary=data.get("context_summary", ""),
            acceptance_checklist=list(data.get("acceptance_checklist") or []),
            confidence=data.get("confidence", 1.0),
            open_questions=list(data.get("open_questions") or []),
            created_at=data.get("created_at", time.time()),
            status=data.get("status", "created"),
            schema_version=data.get("schema_version", "1.0.0"),
            feedback=data.get("feedback"),
        )
