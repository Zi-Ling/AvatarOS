from __future__ import annotations

"""TriggerEngine — rule matching + cooldown + idempotency for the event system.

Evaluates incoming AgentEvents against registered TriggerRules.
Implements cooldown checking to prevent duplicate triggers and
idempotency filtering to avoid re-processing the same event.

Requirements: 4.5, 4.6
"""

import logging
import time
from typing import Dict, List

from .types import AgentEvent, TriggerRule

logger = logging.getLogger(__name__)


class TriggerEngine:
    """Rule matching + cooldown + idempotency."""

    def __init__(self) -> None:
        self._rules: Dict[str, TriggerRule] = {}
        # rule_id → timestamp of last trigger
        self._last_triggered: Dict[str, float] = {}
        # Set of (rule_id, event_id) pairs already processed
        self._processed: set[tuple[str, str]] = set()

    # ── rule management ──

    def add_rule(self, rule: TriggerRule) -> None:
        """Register a trigger rule."""
        self._rules[rule.rule_id] = rule

    def remove_rule(self, rule_id: str) -> None:
        """Unregister a trigger rule."""
        self._rules.pop(rule_id, None)
        self._last_triggered.pop(rule_id, None)

    # ── matching ──

    def match(self, event: AgentEvent) -> List[TriggerRule]:
        """Return rules that match *event*, filtered by cooldown and idempotency.

        Matching logic:
        1. event_pattern exact match against event.event_type
        2. payload_conditions: every key/value in the rule must be present
           and equal in event.payload
        3. Cooldown: skip if rule was triggered within its cooldown window
        4. Idempotency: skip if (rule_id, event_id) was already processed
        """
        now = time.time()
        matched: List[TriggerRule] = []

        for rule in self._rules.values():
            if not rule.enabled:
                continue

            # 1. event_pattern exact match
            if rule.event_pattern != event.event_type:
                continue

            # 2. payload conditions
            if not self._payload_matches(rule.payload_conditions, event.payload):
                continue

            # 3. Idempotency check
            pair = (rule.rule_id, event.event_id)
            if pair in self._processed:
                continue

            # 4. Cooldown check
            last = self._last_triggered.get(rule.rule_id, 0.0)
            if now - last < rule.cooldown:
                continue

            # All checks passed
            self._last_triggered[rule.rule_id] = now
            self._processed.add(pair)
            matched.append(rule)

        # Sort by rule priority descending
        matched.sort(key=lambda r: r.priority, reverse=True)
        return matched

    # ── internals ──

    @staticmethod
    def _payload_matches(conditions: Dict, payload: Dict) -> bool:
        """Return True if every key/value in *conditions* exists in *payload*."""
        for key, expected in conditions.items():
            if key not in payload or payload[key] != expected:
                return False
        return True
