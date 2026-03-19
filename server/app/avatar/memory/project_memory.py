from __future__ import annotations

"""ProjectMemory — project-level persistent knowledge.

Delegates to MemoryManager.knowledge_store for persistence.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from .base import MemoryKind, MemoryRecord


@dataclass
class FailureLesson:
    """A single failure lesson extracted from task execution."""

    lesson_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    error_context: str = ""
    root_cause: str = ""
    resolution: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    schema_version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "lesson_id": self.lesson_id,
            "error_context": self.error_context,
            "root_cause": self.root_cause,
            "resolution": self.resolution,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FailureLesson:
        return cls(
            lesson_id=data.get("lesson_id", str(uuid.uuid4())),
            error_context=data.get("error_context", ""),
            root_cause=data.get("root_cause", ""),
            resolution=data.get("resolution", ""),
            created_at=data.get("created_at", datetime.utcnow().isoformat()),
            schema_version=data.get("schema_version", "1.0.0"),
        )


@dataclass
class ProjectMemory:
    """Project-level persistent knowledge.

    Delegates to MemoryManager.knowledge_store for persistence via
    the ``_memory_manager`` reference (set externally by MemorySystem).
    """

    successful_patterns: list[dict[str, Any]] = field(default_factory=list)
    failure_lessons: list[FailureLesson] = field(default_factory=list)
    project_conventions: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0.0"

    # Optional reference to MemoryManager for persistence (not serialized)
    _memory_manager: Optional[Any] = field(default=None, repr=False, compare=False)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "successful_patterns": [dict(p) for p in self.successful_patterns],
            "failure_lessons": [fl.to_dict() for fl in self.failure_lessons],
            "project_conventions": dict(self.project_conventions),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectMemory:
        return cls(
            successful_patterns=[dict(p) for p in (data.get("successful_patterns") or [])],
            failure_lessons=[
                FailureLesson.from_dict(fl) for fl in (data.get("failure_lessons") or [])
            ],
            project_conventions=dict(data.get("project_conventions") or {}),
            schema_version=data.get("schema_version", "1.0.0"),
        )

    # ------------------------------------------------------------------
    # Domain methods
    # ------------------------------------------------------------------

    def record_lesson(self, error_context: str, root_cause: str, resolution: str) -> None:
        """Record a failure lesson and persist via MemoryManager if available."""
        lesson = FailureLesson(
            error_context=error_context,
            root_cause=root_cause,
            resolution=resolution,
        )
        self.failure_lessons.append(lesson)
        self._persist()

    def record_pattern(self, pattern: dict[str, Any]) -> None:
        """Record a successful pattern and persist via MemoryManager if available."""
        self.successful_patterns.append(dict(pattern))
        self._persist()

    # ------------------------------------------------------------------
    # Persistence helper
    # ------------------------------------------------------------------

    def _persist(self) -> None:
        """Delegate persistence to MemoryManager.knowledge_store if set."""
        if self._memory_manager is None:
            return
        self._memory_manager.set_knowledge("project:memory", self.to_dict())
