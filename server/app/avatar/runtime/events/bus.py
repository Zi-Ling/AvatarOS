from __future__ import annotations

from typing import Callable, List, Dict, Optional, Any
import logging
from collections import defaultdict
import asyncio

from .types import Event, EventType

logger = logging.getLogger(__name__)

# Callback type: function that takes an Event and returns nothing
EventHandler = Callable[[Event], None]


class EventBus:
    """
    A simple synchronous event bus with WebSocket broadcasting support.
    
    Requirements:
    - 21.2: Broadcast graph events via WebSocket
    """
    
    def __init__(self):
        self._subscribers: Dict[EventType, List[EventHandler]] = defaultdict(list)
        self._global_subscribers: List[EventHandler] = []
        self._websocket_broadcaster: Optional[Callable[[Event], None]] = None

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Subscribe to a specific event type."""
        self._subscribers[event_type].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe to all events."""
        self._global_subscribers.append(handler)
    
    def set_websocket_broadcaster(self, broadcaster: Callable[[Event], None]) -> None:
        """
        Set WebSocket broadcaster for real-time updates.
        
        The broadcaster should be a function that takes an Event and broadcasts
        it to connected WebSocket clients.
        
        Args:
            broadcaster: Function to broadcast events via WebSocket
            
        Requirements: 21.2
        """
        self._websocket_broadcaster = broadcaster
        logger.info("WebSocket broadcaster registered with EventBus")

    def publish(self, event: Event) -> None:
        """
        Publish an event to all subscribers.
        
        This method:
        1. Notifies specific event type subscribers
        2. Notifies global subscribers
        3. Broadcasts to WebSocket clients (if broadcaster is set)
        
        Broadcasts on these events:
        - node_started
        - node_completed
        - node_failed
        - graph_completed
        
        Requirements: 21.2
        """
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
        
        # 3. Broadcast to WebSocket clients (Requirement 21.2)
        if self._websocket_broadcaster:
            from .types import EventType as ET
            broadcast_events = {
                ET.GRAPH_STARTED,
                ET.GRAPH_COMPLETED,
                ET.GRAPH_FAILED,
                ET.NODE_STARTED,
                ET.NODE_COMPLETED,
                ET.NODE_FAILED,
            }
            if event.type in broadcast_events:
                try:
                    self._websocket_broadcaster(event)
                except Exception as e:
                    logger.error(f"Error in WebSocket broadcaster: {e}", exc_info=True)
