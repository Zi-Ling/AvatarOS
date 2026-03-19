"""
TaskRuntimeState — semantic summary layer for task execution progress.

V1 core: 5 fields + lightweight plan_deviations.
Includes update methods, JSON serialization, and crash recovery support.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class UpdateSource(str, Enum):
    """Origin of a state update."""
    NODE_STATUS_AGGREGATION = "node_status_aggregation"
    PHASE_SUMMARY = "phase_summary"
    GATE_RESPONSE = "gate_response"
    PLANNER_DECISION = "planner_decision"
    USER_INPUT = "user_input"
    SYSTEM_FALLBACK = "system_fallback"


@dataclass
class CompletedItem:
    """A completed deliverable or milestone."""
    item_id: str
    description: str  # human-readable semantic summary
    timestamp: float
    update_source: UpdateSource


@dataclass
class CurrentBlocker:
    """An active blocker preventing progress."""
    blocker_id: str
    description: str
    blocker_type: str  # "error" / "missing_info" / "waiting_approval"
    update_source: UpdateSource


@dataclass
class DecisionLogEntry:
    """A recorded decision made during execution."""
    decision_id: str
    context: str      # semantic summary of trigger reason
    decision: str     # decision content
    rationale: str    # decision rationale
    update_source: UpdateSource


@dataclass
class TaskRuntimeState:
    """Semantic summary layer — V1 core 5 fields + lightweight plan_deviations."""
    completed_items: List[CompletedItem] = field(default_factory=list)
    current_blockers: List[CurrentBlocker] = field(default_factory=list)
    decision_log: List[DecisionLogEntry] = field(default_factory=list)
    assumption_registry: List[Dict] = field(default_factory=list)
    requirement_changes: List[Dict] = field(default_factory=list)
    plan_deviations: List[Dict] = field(default_factory=list)
    schema_version: str = "1.0.0"


    # ------------------------------------------------------------------
    # Update methods
    # ------------------------------------------------------------------

    def add_completed_item(
        self,
        description: str,
        update_source: UpdateSource,
        item_id: Optional[str] = None,
    ) -> CompletedItem:
        """Record a completed deliverable or milestone."""
        item = CompletedItem(
            item_id=item_id or str(uuid.uuid4())[:8],
            description=description,
            timestamp=time.time(),
            update_source=update_source,
        )
        self.completed_items.append(item)
        return item

    def add_blocker(
        self,
        description: str,
        blocker_type: str,
        update_source: UpdateSource,
        blocker_id: Optional[str] = None,
    ) -> CurrentBlocker:
        """Record an active blocker."""
        blocker = CurrentBlocker(
            blocker_id=blocker_id or str(uuid.uuid4())[:8],
            description=description,
            blocker_type=blocker_type,
            update_source=update_source,
        )
        self.current_blockers.append(blocker)
        return blocker

    def remove_blocker(self, blocker_id: str) -> bool:
        """Remove a resolved blocker. Returns True if found."""
        for i, b in enumerate(self.current_blockers):
            if b.blocker_id == blocker_id:
                self.current_blockers.pop(i)
                return True
        return False

    def add_decision_log(
        self,
        context: str,
        decision: str,
        rationale: str,
        update_source: UpdateSource,
        decision_id: Optional[str] = None,
    ) -> DecisionLogEntry:
        """Record a decision made during execution."""
        entry = DecisionLogEntry(
            decision_id=decision_id or str(uuid.uuid4())[:8],
            context=context,
            decision=decision,
            rationale=rationale,
            update_source=update_source,
        )
        self.decision_log.append(entry)
        return entry

    def add_assumption(
        self,
        assumption_id: str,
        description: str,
        source: str = "inferred",
        status: str = "pending",
    ) -> None:
        """Register an assumption."""
        self.assumption_registry.append({
            "assumption_id": assumption_id,
            "description": description,
            "status": status,
            "source": source,
        })

    def add_plan_deviation(
        self,
        deviation_type: str,
        brief_reason: str,
    ) -> None:
        """Record a plan deviation."""
        self.plan_deviations.append({
            "deviation_type": deviation_type,
            "brief_reason": brief_reason,
        })

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for JSON persistence."""
        def _serialize_item(item: Any) -> Any:
            if isinstance(item, Enum):
                return item.value
            if hasattr(item, "__dataclass_fields__"):
                return {
                    k: _serialize_item(v)
                    for k, v in asdict(item).items()
                }
            if isinstance(item, list):
                return [_serialize_item(i) for i in item]
            if isinstance(item, dict):
                return {k: _serialize_item(v) for k, v in item.items()}
            return item

        return _serialize_item(self)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskRuntimeState":
        """Deserialize from dict."""
        state = cls(schema_version=data.get("schema_version", "1.0.0"))

        for item_data in data.get("completed_items", []):
            state.completed_items.append(CompletedItem(
                item_id=item_data["item_id"],
                description=item_data["description"],
                timestamp=item_data["timestamp"],
                update_source=UpdateSource(item_data["update_source"]),
            ))

        for blocker_data in data.get("current_blockers", []):
            state.current_blockers.append(CurrentBlocker(
                blocker_id=blocker_data["blocker_id"],
                description=blocker_data["description"],
                blocker_type=blocker_data["blocker_type"],
                update_source=UpdateSource(blocker_data["update_source"]),
            ))

        for entry_data in data.get("decision_log", []):
            state.decision_log.append(DecisionLogEntry(
                decision_id=entry_data["decision_id"],
                context=entry_data["context"],
                decision=entry_data["decision"],
                rationale=entry_data["rationale"],
                update_source=UpdateSource(entry_data["update_source"]),
            ))

        state.assumption_registry = data.get("assumption_registry", [])
        state.requirement_changes = data.get("requirement_changes", [])
        state.plan_deviations = data.get("plan_deviations", [])
        return state

    @classmethod
    def from_json(cls, json_str: str) -> "TaskRuntimeState":
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))
