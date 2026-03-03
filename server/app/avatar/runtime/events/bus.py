from __future__ import annotations

from typing import Callable, List, Dict
import logging
from collections import defaultdict

from .types import Event, EventType

logger = logging.getLogger(__name__)

# Callback type: function that takes an Event and returns nothing
EventHandler = Callable[[Event], None]


class EventBus:
    """
    A simple synchronous event bus.
    """
    
    def __init__(self):
        self._subscribers: Dict[EventType, List[EventHandler]] = defaultdict(list)
        self._global_subscribers: List[EventHandler] = []

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Subscribe to a specific event type."""
        self._subscribers[event_type].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe to all events."""
        self._global_subscribers.append(handler)

    def publish(self, event: Event) -> None:
        """Publish an event to all subscribers."""
        # 1. Notify specific subscribers
        if event.type in self._subscribers:
            for handler in self._subscribers[event.type]:
                try:
                    handler(event)
                except Exception as e:
                    logger.error(f"Error in event handler for {event.type}: {e}", exc_info=True)

        # 2. Notify global subscribers
        for handler in self._global_subscribers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Error in global event handler: {e}", exc_info=True)

