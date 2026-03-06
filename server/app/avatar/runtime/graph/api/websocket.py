"""
WebSocket Endpoint for Real-Time Graph Updates

This module provides WebSocket support for broadcasting graph execution updates
to connected clients in real-time.

Requirements: 21.1, 21.2, 21.3, 21.7
"""

from __future__ import annotations
from typing import Dict, Set, Any, Optional
import logging
import json
import asyncio
from datetime import datetime

logger = logging.getLogger(__name__)


class WebSocketManager:
    """
    Manages WebSocket connections and broadcasts graph events.
    
    This class:
    - Maintains active WebSocket connections
    - Broadcasts node status changes to clients
    - Supports reconnection with state synchronization
    - Filters events by graph_id for targeted broadcasting
    
    Requirements:
    - 21.1: WebSocket endpoint for graph state updates
    - 21.2: Broadcast node status changes
    - 21.3: Include graph_id, node_id, status, outputs, error_message
    - 21.7: Support reconnection with state synchronization
    """
    
    def __init__(self):
        """Initialize WebSocket manager"""
        # Store connections by graph_id for targeted broadcasting
        self._connections: Dict[str, Set[Any]] = {}
        # Store all connections for global broadcasts
        self._all_connections: Set[Any] = set()
        # Store latest state for reconnection sync
        self._graph_states: Dict[str, Dict[str, Any]] = {}
        
        logger.info("WebSocketManager initialized")
    
    async def connect(
        self,
        websocket: Any,
        graph_id: Optional[str] = None
    ) -> None:
        """
        Register a new WebSocket connection.
        
        Args:
            websocket: WebSocket connection object
            graph_id: Optional graph ID to subscribe to specific graph updates
            
        Requirements: 21.1
        """
        self._all_connections.add(websocket)
        
        if graph_id:
            if graph_id not in self._connections:
                self._connections[graph_id] = set()
            self._connections[graph_id].add(websocket)
            
            logger.info(f"WebSocket connected for graph {graph_id}")
            
            # Send current state for reconnection sync (Requirement 21.7)
            if graph_id in self._graph_states:
                await self._send_state_sync(websocket, graph_id)
        else:
            logger.info("WebSocket connected (global)")
    
    async def disconnect(
        self,
        websocket: Any,
        graph_id: Optional[str] = None
    ) -> None:
        """
        Unregister a WebSocket connection.
        
        Args:
            websocket: WebSocket connection object
            graph_id: Optional graph ID if subscribed to specific graph
        """
        self._all_connections.discard(websocket)
        
        if graph_id and graph_id in self._connections:
            self._connections[graph_id].discard(websocket)
            if not self._connections[graph_id]:
                del self._connections[graph_id]
            
            logger.info(f"WebSocket disconnected from graph {graph_id}")
        else:
            logger.info("WebSocket disconnected (global)")
    
    async def broadcast_event(self, event: Any) -> None:
        """
        Broadcast an event to relevant WebSocket clients.
        
        This method extracts graph_id from the event and broadcasts to:
        - Clients subscribed to that specific graph
        - Global clients (subscribed to all graphs)
        
        Args:
            event: Event object with type and data
            
        Requirements: 21.2, 21.3
        """
        try:
            # Extract event data
            event_type = event.type if hasattr(event, 'type') else str(event)
            event_data = event.data if hasattr(event, 'data') else {}
            
            # Extract graph_id from event data
            graph_id = event_data.get('graph_id')
            
            if not graph_id:
                logger.warning(f"Event {event_type} has no graph_id, skipping broadcast")
                return
            
            # Build message (Requirement 21.3)
            message = {
                'type': event_type,
                'graph_id': graph_id,
                'timestamp': datetime.now().isoformat(),
                'data': event_data,
            }
            
            # Update graph state for reconnection sync
            self._update_graph_state(graph_id, event_type, event_data)
            
            # Get target connections
            target_connections = set()
            
            # Add graph-specific connections
            if graph_id in self._connections:
                target_connections.update(self._connections[graph_id])
            
            # Broadcast to all target connections
            if target_connections:
                await self._broadcast_to_connections(target_connections, message)
                logger.debug(
                    f"Broadcasted {event_type} for graph {graph_id} "
                    f"to {len(target_connections)} clients"
                )
            
        except Exception as e:
            logger.error(f"Error broadcasting event: {e}", exc_info=True)
    
    async def _broadcast_to_connections(
        self,
        connections: Set[Any],
        message: Dict[str, Any]
    ) -> None:
        """
        Send message to multiple WebSocket connections.
        
        Args:
            connections: Set of WebSocket connections
            message: Message dictionary to send
        """
        if not connections:
            return
        
        # Convert message to JSON
        message_json = json.dumps(message)
        
        # Send to all connections concurrently
        tasks = []
        for websocket in connections:
            tasks.append(self._send_message(websocket, message_json))
        
        # Wait for all sends to complete
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _send_message(
        self,
        websocket: Any,
        message: str
    ) -> None:
        """
        Send message to a single WebSocket connection.
        
        Args:
            websocket: WebSocket connection
            message: JSON string message
        """
        try:
            await websocket.send(message)
        except Exception as e:
            logger.error(f"Error sending message to WebSocket: {e}")
            # Connection might be closed, will be cleaned up on next disconnect
    
    def _update_graph_state(
        self,
        graph_id: str,
        event_type: str,
        event_data: Dict[str, Any]
    ) -> None:
        """
        Update stored graph state for reconnection sync.
        
        Args:
            graph_id: Graph ID
            event_type: Event type
            event_data: Event data
            
        Requirements: 21.7
        """
        if graph_id not in self._graph_states:
            self._graph_states[graph_id] = {
                'graph_id': graph_id,
                'status': 'pending',
                'nodes': {},
                'last_update': datetime.now().isoformat(),
            }
        
        state = self._graph_states[graph_id]
        
        # Update based on event type
        if event_type == 'graph_started':
            state['status'] = 'running'
        elif event_type == 'graph_completed':
            state['status'] = 'completed'
        elif event_type == 'graph_failed':
            state['status'] = 'failed'
        elif event_type == 'node_started':
            node_id = event_data.get('node_id')
            if node_id:
                state['nodes'][node_id] = {
                    'status': 'running',
                    'capability': event_data.get('capability'),
                }
        elif event_type == 'node_completed':
            node_id = event_data.get('node_id')
            if node_id:
                state['nodes'][node_id] = {
                    'status': 'completed',
                    'execution_time': event_data.get('execution_time'),
                    'retry_count': event_data.get('retry_count', 0),
                }
        elif event_type == 'node_failed':
            node_id = event_data.get('node_id')
            if node_id:
                state['nodes'][node_id] = {
                    'status': 'failed',
                    'error': event_data.get('error'),
                    'retry_count': event_data.get('retry_count', 0),
                }
        
        state['last_update'] = datetime.now().isoformat()
    
    async def _send_state_sync(
        self,
        websocket: Any,
        graph_id: str
    ) -> None:
        """
        Send current graph state to a reconnecting client.
        
        Args:
            websocket: WebSocket connection
            graph_id: Graph ID
            
        Requirements: 21.7
        """
        if graph_id not in self._graph_states:
            return
        
        state = self._graph_states[graph_id]
        
        message = {
            'type': 'state_sync',
            'graph_id': graph_id,
            'timestamp': datetime.now().isoformat(),
            'data': state,
        }
        
        try:
            await websocket.send(json.dumps(message))
            logger.info(f"Sent state sync for graph {graph_id}")
        except Exception as e:
            logger.error(f"Error sending state sync: {e}")
    
    def get_connection_count(self, graph_id: Optional[str] = None) -> int:
        """
        Get number of active connections.
        
        Args:
            graph_id: Optional graph ID to get count for specific graph
            
        Returns:
            Number of active connections
        """
        if graph_id:
            return len(self._connections.get(graph_id, set()))
        return len(self._all_connections)
    
    def clear_graph_state(self, graph_id: str) -> None:
        """
        Clear stored state for a graph.
        
        Args:
            graph_id: Graph ID to clear
        """
        if graph_id in self._graph_states:
            del self._graph_states[graph_id]
            logger.debug(f"Cleared state for graph {graph_id}")


# Global WebSocket manager instance
_websocket_manager = WebSocketManager()


def get_websocket_manager() -> WebSocketManager:
    """Get the global WebSocket manager instance"""
    return _websocket_manager


def create_event_broadcaster() -> Any:
    """
    Create a broadcaster function for EventBus integration.
    
    This function can be passed to EventBus.set_websocket_broadcaster()
    to enable automatic broadcasting of events.
    
    Returns:
        Broadcaster function
        
    Requirements: 21.2
    """
    manager = get_websocket_manager()
    
    def broadcaster(event: Any) -> None:
        """Broadcast event via WebSocket"""
        # Schedule the async broadcast
        asyncio.create_task(manager.broadcast_event(event))
    
    return broadcaster
