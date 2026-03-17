"""
Narrative data models — dataclasses for the Execution Narrative Layer.

Defines the core data structures used by NarrativeMapper and NarrativeManager:
- NarrativeEvent: the atomic event pushed via WebSocket
- NarrativeEventPayload: Mapper output (no sequence/event_id/run_id/timestamp)
- EventMapping: internal_event_type → narrative mapping configuration
- TranslationContext: contextual information passed to the Mapper for translation
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal


@dataclass
class NarrativeEvent:
    """Atomic narrative event — the minimal unit pushed via WebSocket."""

    event_id: str               # UUID, globally unique for idempotent dedup
    run_id: str                 # Associated Run ID
    step_id: str                # Associated step; "__run__" for run-level events
    event_type: str             # Narrative event type (e.g. "tool_started")
    source_event_type: str      # Original internal event type (e.g. "step.start")
    level: Literal["major", "minor"]
    phase: str                  # Phase label (e.g. "executing", "verifying")
    status: str                 # Status (e.g. "running", "completed", "failed")
    description: str            # User-facing description in natural language
    timestamp: str              # ISO 8601 timestamp
    sequence: int               # Monotonically increasing within a single run
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NarrativeEventPayload:
    """Mapper output payload — does not contain sequence, event_id, run_id, or timestamp."""

    event_type: str             # Narrative event type
    source_event_type: str      # Original internal event type
    level: Literal["major", "minor"]
    phase: str                  # Phase label
    status: str                 # Status
    description: str            # User-facing description
    step_id: str                # Associated step ID or "__run__"
    metadata: dict = field(default_factory=dict)


@dataclass
class EventMapping:
    """Mapping configuration from internal event type to narrative event."""

    event_type: str             # Narrative event type
    level: Literal["major", "minor"]
    phase: str                  # Phase label
    status: str                 # Status
    template: str               # Template string with placeholders like {skill_name}


@dataclass
class TranslationContext:
    """Contextual information passed to the Mapper for translation."""

    skill_name: str | None = None
    params_summary: str | None = None       # e.g. "config.json"
    semantic_label: str | None = None       # Highest priority for description
    output_summary: str | None = None
    artifact_type: str | None = None        # image/file/table/code
    artifact_label: str | None = None
    retry_count: int | None = None
    reason: str | None = None
    error_message: str | None = None
