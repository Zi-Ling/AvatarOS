from __future__ import annotations

"""WorkingMemory — current task immediate control state.

Wraps existing TaskRuntimeState and SessionContext.
Large artifacts store only artifact_ref; single intermediate results max 4KB inline.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Optional

# 4KB inline limit for single intermediate results
_MAX_INLINE_BYTES = 4096


@dataclass
class WorkingMemory:
    """Current task immediate control state.

    Fields:
        task_id: Unique task identifier.
        task_definition: Current TaskDefinition snapshot (dict).
        execution_state_ref: Reference to current ExecutionGraph state.
        decision_context: Decision context stack.
        attention_focus: Current focus description.
        artifact_refs: Large artifact references (no inline payload).
        resume_anchor: Restore anchor point for suspend/resume.
        schema_version: Schema version string.
    """

    task_id: str = ""
    task_definition: Optional[dict[str, Any]] = None
    execution_state_ref: Optional[str] = None
    decision_context: list[dict[str, Any]] = field(default_factory=list)
    attention_focus: str = ""
    artifact_refs: list[str] = field(default_factory=list)
    resume_anchor: Optional[dict[str, Any]] = None
    schema_version: str = "1.0.0"

    # Wrapped existing components (not serialized)
    _task_runtime_state: Optional[Any] = field(default=None, repr=False, compare=False)
    _session_context: Optional[Any] = field(default=None, repr=False, compare=False)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_definition": self.task_definition,
            "execution_state_ref": self.execution_state_ref,
            "decision_context": [dict(d) for d in self.decision_context],
            "attention_focus": self.attention_focus,
            "artifact_refs": list(self.artifact_refs),
            "resume_anchor": dict(self.resume_anchor) if self.resume_anchor is not None else None,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkingMemory:
        return cls(
            task_id=data.get("task_id", ""),
            task_definition=data.get("task_definition"),
            execution_state_ref=data.get("execution_state_ref"),
            decision_context=[dict(d) for d in (data.get("decision_context") or [])],
            attention_focus=data.get("attention_focus", ""),
            artifact_refs=list(data.get("artifact_refs") or []),
            resume_anchor=dict(data["resume_anchor"]) if data.get("resume_anchor") is not None else None,
            schema_version=data.get("schema_version", "1.0.0"),
        )

    def snapshot(self) -> bytes:
        """Serialize current state to JSON bytes."""
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")

    @classmethod
    def restore(cls, data: bytes) -> WorkingMemory:
        """Restore from JSON bytes. Round-trip preserves all fields."""
        return cls.from_dict(json.loads(data.decode("utf-8")))

    # ------------------------------------------------------------------
    # Inline size enforcement
    # ------------------------------------------------------------------

    @staticmethod
    def check_inline_size(value: Any) -> bool:
        """Return True if *value* fits within the 4 KB inline limit."""
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        return len(raw) <= _MAX_INLINE_BYTES
