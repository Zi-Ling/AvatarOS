import asyncio
import logging
import json
from dataclasses import asdict
from datetime import datetime

from .types import Event, EventType
from .bus import EventBus
from app.io.manager import SocketManager

logger = logging.getLogger(__name__)

class SocketBridge:
    """
    Bridges the synchronous EventBus with the asynchronous SocketManager.
    Listens to all internal events and broadcasts them to connected WebSocket clients.
    """
    
    def __init__(self, event_bus: EventBus, socket_manager: SocketManager):
        self.event_bus = event_bus
        self.socket_manager = socket_manager
        self._loop = None  # Reference to the running event loop

    def start(self):
        """
        Subscribe to all events on the bus.
        Must be called after the event loop is running (e.g. inside FastAPI startup).
        """
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("SocketBridge started without a running event loop. Async emission might fail.")
        
        logger.info("Starting EventBus -> SocketIO Bridge")
        self.event_bus.subscribe_all(self._handle_event)

    def _handle_event(self, event: Event) -> None:
        """
        Synchronous callback called by EventBus.
        Schedules the async emission task on the event loop.
        """
        # 调试日志：显示事件类型和 step_id（仅在需要调试时取消注释）
        # step_info = f" [Step: {event.step_id}]" if event.step_id else ""
        # logger.debug(f"BRIDGE: Handling event {event.type.value}{step_info} - Source: {event.source}")
        
        if self._loop and self._loop.is_running():
            try:
                payload = self._serialize_event(event)
                
                # Check if we are in the same thread as the loop
                try:
                    # If we are in the loop thread, get_running_loop() will match self._loop
                    # or at least return without error
                    current_loop = asyncio.get_running_loop()
                    if current_loop == self._loop:
                        # Same loop: Create task directly
                        current_loop.create_task(self.socket_manager.emit("server_event", payload))
                        return
                except RuntimeError:
                    # No running loop in current thread -> we are in a worker thread
                    pass

                # Different thread: Use threadsafe
                asyncio.run_coroutine_threadsafe(
                    self.socket_manager.emit("server_event", payload),
                    self._loop
                )
            except Exception as e:
                logger.error(f"Error bridging event {event.type}: {e}")
        else:
            logger.warning(f"Cannot emit event {event.type}: Event loop not available")

    def _serialize_event(self, event: Event) -> dict:
        """
        Converts the Event dataclass to a JSON-ready dictionary.
        Handles non-serializable fields if necessary.
        """
        # Basic serialization using asdict
        data = asdict(event)
        
        # Convert enum to string for frontend consumption
        data['type'] = event.type.value
        
        # Ensure step_id is at the top level for frontend compatibility
        # 前端期望: event.step_id
        if event.step_id:
            data['step_id'] = event.step_id
        
        # Ensure timestamp is ISO string
        if isinstance(data.get('timestamp'), (int, float)):
            # If timestamp is unix time
            pass 
        # Note: Event class uses default_factory=lambda: time.time() which returns float
        
        # If the event payload has complex objects, we might need more processing here.
        # For now, we assume payload is JSON serializable.
        return data
