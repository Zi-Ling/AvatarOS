from __future__ import annotations

"""EventBusV2 — unified event bus with trigger rule matching.

Wraps EventSourceRegistry + TriggerEngine into a single subsystem
that AgentLoop._sense_phase() can consume via drain_pending() and
match_trigger_rules().

Falls back to the existing EventBus on exception.

Requirements: 4.1, 4.5, 4.6
"""

import logging
from typing import Any, List, Optional

from .types import AgentEvent, TriggerRule
from .trigger_engine import TriggerEngine
from .event_source_registry import EventSourceRegistry

logger = logging.getLogger(__name__)


class EventBusV2:
    """Unified event bus with trigger rule matching.

    Provides:
    - publish(event): enqueue an AgentEvent
    - drain_pending(): return and clear all pending events
    - match_trigger_rules(event): evaluate TriggerRules against an event
    - add_rule / remove_rule: manage trigger rules
    - register_source / get_health: manage EventSource adapters
    """

    def __init__(
        self,
        trigger_engine: Optional[TriggerEngine] = None,
        source_registry: Optional[EventSourceRegistry] = None,
    ) -> None:
        self._trigger_engine = trigger_engine or TriggerEngine()
        self._source_registry = source_registry or EventSourceRegistry()
        self._pending: List[AgentEvent] = []

    # ── Event publishing ──

    def publish(self, event: AgentEvent) -> None:
        """Enqueue an event for processing in the next sense phase."""
        self._pending.append(event)

    async def drain_pending(self) -> List[AgentEvent]:
        """Return and clear all pending events."""
        events = list(self._pending)
        self._pending.clear()
        return events

    # ── Trigger rule matching ──

    def match_trigger_rules(self, event: AgentEvent) -> List[TriggerRule]:
        """Evaluate all registered TriggerRules against an event."""
        return self._trigger_engine.match(event)

    def add_rule(self, rule: TriggerRule) -> None:
        """Register a trigger rule."""
        self._trigger_engine.add_rule(rule)

    def remove_rule(self, rule_id: str) -> None:
        """Unregister a trigger rule."""
        self._trigger_engine.remove_rule(rule_id)

    # ── Source management ──

    def register_source(self, source: Any) -> None:
        """Register an EventSource adapter."""
        self._source_registry.register(source)

    def get_health(self) -> dict[str, bool]:
        """Return health status of all registered sources."""
        return self._source_registry.get_health()
