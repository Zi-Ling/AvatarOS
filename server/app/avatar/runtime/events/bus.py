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


# ---------------------------------------------------------------------------
# EventBusV2 — inherits EventBus, delegates to EventBuffer / TriggerEngine /
# EventSourceRegistry for backpressure, rule matching, and source management.
#
# Requirements: 4.1, 4.4, 4.8
# ---------------------------------------------------------------------------

from .buffer import EventBuffer
from .trigger_engine import TriggerEngine
from .event_source_registry import EventSourceRegistry
from .types import AgentEvent, TriggerRule


class EventBusV2(EventBus):
    """Extended event bus with backpressure, trigger rules, and source management.

    Inherits from EventBus to preserve subscribe() and WebSocket broadcasting.
    Internal complexity is delegated to:
      - EventBuffer: backpressure + priority buffering
      - TriggerEngine: rule matching + cooldown + idempotency
      - EventSourceRegistry: source registration + health + reconnection
    """

    def __init__(
        self,
        event_buffer: Optional[EventBuffer] = None,
        trigger_engine: Optional[TriggerEngine] = None,
        source_registry: Optional[EventSourceRegistry] = None,
    ) -> None:
        super().__init__()
        self._buffer = event_buffer or EventBuffer()
        self._trigger_engine = trigger_engine or TriggerEngine()
        self._source_registry = source_registry or EventSourceRegistry()

    # ── publish (sync, compatible with parent) ──

    def publish(self, event: Event) -> None:
        """Publish an event: parent broadcast + buffer to EventBuffer.

        If *event* is an ``Event`` (legacy), it is broadcast via the parent
        class.  If it is an ``AgentEvent`` (V2), it is also buffered for
        ``drain_pending()``.  A plain ``Event`` is converted to an
        ``AgentEvent`` before buffering so that the sense phase always
        receives a uniform type.
        """
        # Parent handles WebSocket broadcasting and subscriber notification
        super().publish(event)

        # Buffer for AgentLoop._sense_phase()
        if isinstance(event, AgentEvent):
            self._buffer.enqueue(event)
        else:
            # Wrap legacy Event as AgentEvent for the buffer
            agent_event = AgentEvent(
                event_type=event.type.value if hasattr(event.type, "value") else str(event.type),
                source=event.source,
                timestamp=event.timestamp,
                payload=dict(event.payload),
                priority="medium",
            )
            self._buffer.enqueue(agent_event)

    # ── drain (for AgentLoop._sense_phase()) ──

    async def drain_pending(self) -> List[AgentEvent]:
        """Return and clear all buffered events, highest priority first."""
        return self._buffer.drain()

    # ── source management proxies ──

    def register_source(self, source: Any) -> None:
        """Register an EventSource adapter."""
        self._source_registry.register(source)

    def unregister_source(self, source_id: str) -> None:
        """Unregister an EventSource adapter."""
        self._source_registry.unregister(source_id)

    # ── trigger rule proxies ──

    def add_trigger_rule(self, rule: TriggerRule) -> None:
        """Register a TriggerRule."""
        self._trigger_engine.add_rule(rule)

    def remove_trigger_rule(self, rule_id: str) -> None:
        """Unregister a TriggerRule."""
        self._trigger_engine.remove_rule(rule_id)

    def match_trigger_rules(self, event: AgentEvent) -> List[TriggerRule]:
        """Return matching TriggerRules for *event* (cooldown-filtered)."""
        return self._trigger_engine.match(event)

    # ── health ──

    def get_source_health(self) -> Dict[str, bool]:
        """Return health status of all registered EventSources."""
        return self._source_registry.get_health()

    async def reconnect_degraded_sources(self) -> None:
        """Attempt to reconnect degraded EventSources."""
        await self._source_registry.reconnect_degraded()
