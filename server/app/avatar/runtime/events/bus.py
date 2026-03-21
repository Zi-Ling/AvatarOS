from __future__ import annotations

"""EventBus — unified event bus with backpressure, trigger rules, and source management.

Provides:
- Synchronous publish/subscribe with WebSocket broadcasting
- EventBuffer for backpressure + priority buffering (AgentLoop sense phase)
- TriggerEngine for rule matching + cooldown + idempotency
- EventSourceRegistry for source registration + health + reconnection

Requirements: 4.1, 4.4, 4.8, 21.2
"""

from typing import Callable, List, Dict, Optional, Any
import logging
from collections import defaultdict

from .types import Event, EventType, AgentEvent, TriggerRule
from .buffer import EventBuffer
from .trigger_engine import TriggerEngine
from .event_source_registry import EventSourceRegistry

logger = logging.getLogger(__name__)

EventHandler = Callable[[Event], None]


class EventBus:
    """Unified event bus with backpressure, trigger rules, and source management.

    Core capabilities:
    - subscribe / subscribe_all / publish: synchronous pub/sub
    - WebSocket broadcasting for graph events
    - EventBuffer: backpressure + priority buffering for AgentLoop
    - TriggerEngine: rule matching + cooldown + idempotency
    - EventSourceRegistry: source registration + health + reconnection
    """

    def __init__(
        self,
        event_buffer: Optional[EventBuffer] = None,
        trigger_engine: Optional[TriggerEngine] = None,
        source_registry: Optional[EventSourceRegistry] = None,
    ) -> None:
        self._subscribers: Dict[EventType, List[EventHandler]] = defaultdict(list)
        self._global_subscribers: List[EventHandler] = []
        self._websocket_broadcaster: Optional[Callable[[Event], None]] = None
        self._buffer = event_buffer or EventBuffer()
        self._trigger_engine = trigger_engine or TriggerEngine()
        self._source_registry = source_registry or EventSourceRegistry()

    # ── Subscribe / Broadcast ───────────────────────────────────────────

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Subscribe to a specific event type."""
        self._subscribers[event_type].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe to all events."""
        self._global_subscribers.append(handler)

    def set_websocket_broadcaster(self, broadcaster: Callable[[Event], None]) -> None:
        """Set WebSocket broadcaster for real-time updates."""
        self._websocket_broadcaster = broadcaster
        logger.info("WebSocket broadcaster registered with EventBus")

    # ── Publish ─────────────────────────────────────────────────────────

    def publish(self, event: Event) -> None:
        """Publish an event: notify subscribers + WebSocket broadcast + buffer.

        If event is an AgentEvent, it is buffered directly.
        If event is a plain Event, it is wrapped as AgentEvent before buffering.
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

        # 3. Broadcast to WebSocket clients
        if self._websocket_broadcaster:
            broadcast_events = {
                EventType.GRAPH_STARTED,
                EventType.GRAPH_COMPLETED,
                EventType.GRAPH_FAILED,
                EventType.NODE_STARTED,
                EventType.NODE_COMPLETED,
                EventType.NODE_FAILED,
            }
            if event.type in broadcast_events:
                try:
                    self._websocket_broadcaster(event)
                except Exception as e:
                    logger.error(f"Error in WebSocket broadcaster: {e}", exc_info=True)

        # 4. Buffer for AgentLoop sense phase
        if isinstance(event, AgentEvent):
            self._buffer.enqueue(event)
        else:
            agent_event = AgentEvent(
                event_type=event.type.value if hasattr(event.type, "value") else str(event.type),
                source=event.source,
                timestamp=event.timestamp,
                payload=dict(event.payload),
                priority="medium",
            )
            self._buffer.enqueue(agent_event)

    # ── Drain (for AgentLoop sense phase) ───────────────────────────────

    async def drain_pending(self) -> List[AgentEvent]:
        """Return and clear all buffered events, highest priority first."""
        return self._buffer.drain()

    # ── Source management ───────────────────────────────────────────────

    def register_source(self, source: Any) -> None:
        """Register an EventSource adapter."""
        self._source_registry.register(source)

    def unregister_source(self, source_id: str) -> None:
        """Unregister an EventSource adapter."""
        self._source_registry.unregister(source_id)

    def get_source_health(self) -> Dict[str, bool]:
        """Return health status of all registered EventSources."""
        return self._source_registry.get_health()

    async def reconnect_degraded_sources(self) -> None:
        """Attempt to reconnect degraded EventSources."""
        await self._source_registry.reconnect_degraded()

    # ── Trigger rule management ─────────────────────────────────────────

    def add_trigger_rule(self, rule: TriggerRule) -> None:
        """Register a TriggerRule."""
        self._trigger_engine.add_rule(rule)

    def remove_trigger_rule(self, rule_id: str) -> None:
        """Unregister a TriggerRule."""
        self._trigger_engine.remove_rule(rule_id)

    def match_trigger_rules(self, event: AgentEvent) -> List[TriggerRule]:
        """Return matching TriggerRules for event (cooldown-filtered)."""
        return self._trigger_engine.match(event)
