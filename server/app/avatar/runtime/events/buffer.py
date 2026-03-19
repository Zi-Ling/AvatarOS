from __future__ import annotations

"""EventBuffer — backpressure + priority buffering for the Agent event system.

Provides a bounded buffer that retains the highest-priority events when full,
discarding the lowest-priority events and logging a warning.

Requirements: 4.7
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import AgentEvent

logger = logging.getLogger(__name__)

# Priority ordering: higher index = higher priority
_PRIORITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

DEFAULT_MAX_SIZE = 1000


def _priority_key(event: AgentEvent) -> int:
    """Return numeric priority for sorting. Unknown priorities default to 0."""
    return _PRIORITY_ORDER.get(getattr(event, "priority", "medium"), 0)


class EventBuffer:
    """Backpressure + priority buffering.

    When the buffer is full (``max_size`` reached), the lowest-priority event
    is discarded and a warning is logged.
    """

    def __init__(self, max_size: int = DEFAULT_MAX_SIZE) -> None:
        self._max_size = max_size
        self._buffer: list[AgentEvent] = []

    # ── public API ──

    def enqueue(self, event: AgentEvent) -> None:
        """Add an event to the buffer.

        If the buffer is at capacity, discard the lowest-priority event
        (which may be the incoming event itself) and log a warning.
        """
        if len(self._buffer) < self._max_size:
            self._buffer.append(event)
            return

        # Buffer full — find the minimum-priority event
        min_event = min(self._buffer, key=_priority_key)
        incoming_priority = _priority_key(event)
        min_priority = _priority_key(min_event)

        if incoming_priority > min_priority:
            # Replace the lowest-priority event with the incoming one
            self._buffer.remove(min_event)
            self._buffer.append(event)
            logger.warning(
                "[EventBuffer] buffer full (%d), discarded lowest-priority event "
                "(priority=%s, event_type=%s)",
                self._max_size,
                getattr(min_event, "priority", "unknown"),
                getattr(min_event, "event_type", "unknown"),
            )
        else:
            # Incoming event is the lowest priority — discard it
            logger.warning(
                "[EventBuffer] buffer full (%d), discarded incoming event "
                "(priority=%s, event_type=%s)",
                self._max_size,
                getattr(event, "priority", "unknown"),
                getattr(event, "event_type", "unknown"),
            )

    def drain(self) -> list[AgentEvent]:
        """Remove and return all buffered events, ordered by priority (highest first)."""
        events = sorted(self._buffer, key=_priority_key, reverse=True)
        self._buffer.clear()
        return events

    def size(self) -> int:
        """Return the current number of buffered events."""
        return len(self._buffer)
