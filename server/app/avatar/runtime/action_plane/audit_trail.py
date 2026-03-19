"""AuditTrail — append-only audit log for ActionPlane operations.

Requirements: 8.5, 10.9
"""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class AuditTrailEntry:
    """Single audit record for an ActionPlane operation."""

    audit_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    action_id: str = ""
    executor_id: str = ""
    executor_type: str = ""
    permission_tier: str = ""
    requester_id: str = ""
    action_description: str = ""
    input_params_summary: str = ""
    output_result_summary: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    status: str = ""  # success / failed / denied
    approval_info: Optional[dict[str, Any]] = None
    schema_version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "action_id": self.action_id,
            "executor_id": self.executor_id,
            "executor_type": self.executor_type,
            "permission_tier": self.permission_tier,
            "requester_id": self.requester_id,
            "action_description": self.action_description,
            "input_params_summary": self.input_params_summary,
            "output_result_summary": self.output_result_summary,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "approval_info": self.approval_info,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditTrailEntry:
        return cls(
            audit_id=data.get("audit_id", str(uuid.uuid4())),
            action_id=data.get("action_id", ""),
            executor_id=data.get("executor_id", ""),
            executor_type=data.get("executor_type", ""),
            permission_tier=data.get("permission_tier", ""),
            requester_id=data.get("requester_id", ""),
            action_description=data.get("action_description", ""),
            input_params_summary=data.get("input_params_summary", ""),
            output_result_summary=data.get("output_result_summary", ""),
            started_at=data.get("started_at", 0.0),
            completed_at=data.get("completed_at", 0.0),
            status=data.get("status", ""),
            approval_info=data.get("approval_info"),
            schema_version=data.get("schema_version", "1.0.0"),
        )


class AuditTrail:
    """Append-only audit log. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[AuditTrailEntry] = []

    def append(self, entry: AuditTrailEntry) -> None:
        """Append an audit entry. Append-only — entries cannot be modified or deleted."""
        with self._lock:
            self._entries.append(entry)
        logger.debug(
            "[AuditTrail] appended audit_id=%s action_id=%s status=%s",
            entry.audit_id,
            entry.action_id,
            entry.status,
        )

    def query(
        self,
        filters: Optional[dict[str, Any]] = None,
        limit: int = 100,
    ) -> list[AuditTrailEntry]:
        """Query audit entries with optional filters.

        Supported filter keys: action_id, executor_id, requester_id, status.
        """
        filters = filters or {}
        with self._lock:
            results = list(self._entries)

        for key, value in filters.items():
            results = [e for e in results if getattr(e, key, None) == value]

        return results[:limit]

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._entries)
