"""HandoffEnvelope — 结构化交接信封.

Requirements: 9.1, 9.3
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict


HANDOFF_STATUSES = (
    "created", "validated", "delivered", "received",
    "completed", "rejected", "cancelled", "expired",
)


@dataclass
class HandoffEnvelope:
    """结构化交接信封."""
    envelope_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_role: str = ""
    source_instance_id: str = ""
    target_role: str = ""
    target_instance_id: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    context_summary: str = ""
    task_id: str = ""
    created_at: float = field(default_factory=time.time)
    status: str = "created"
    schema_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "envelope_id": self.envelope_id,
            "source_role": self.source_role,
            "source_instance_id": self.source_instance_id,
            "target_role": self.target_role,
            "target_instance_id": self.target_instance_id,
            "payload": dict(self.payload),
            "context_summary": self.context_summary,
            "task_id": self.task_id,
            "created_at": self.created_at,
            "status": self.status,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> HandoffEnvelope:
        return cls(
            envelope_id=data.get("envelope_id", str(uuid.uuid4())),
            source_role=data.get("source_role", ""),
            source_instance_id=data.get("source_instance_id", ""),
            target_role=data.get("target_role", ""),
            target_instance_id=data.get("target_instance_id", ""),
            payload=dict(data.get("payload") or {}),
            context_summary=data.get("context_summary", ""),
            task_id=data.get("task_id", ""),
            created_at=data.get("created_at", time.time()),
            status=data.get("status", "created"),
            schema_version=data.get("schema_version", "1.0.0"),
        )
