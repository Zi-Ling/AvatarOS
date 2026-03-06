"""
REST API Endpoints for Graph Operations

This module provides REST API endpoints for graph execution and management.

Requirements: 26.7, 32.6, 33.8
"""

from __future__ import annotations
from typing import Dict, Any, Optional
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class GraphAPI:
    """
    REST API for graph operations.
    
    This class provides endpoints for:
    - Executing graphs with intent
    - Getting graph state
    - Getting execution status
    - Getting execution cost
    - Getting version history
    - Pausing/resuming/cancelling execution
    
    Requirements:
    - 26.7: Execute graph API
    - 32.6: Get execution cost API
    - 33.8: Get version history API
    """
    
    def __init__(
        self,
        controller: Any,
        runtime: Any,
        version_manager: Optional[Any] = None
    ):
        """
        Initialize GraphAPI.
        
        Args:
            controller: GraphController instance
            runtime: GraphRuntime instance
            version_manager: Optional GraphVersionManager instance
        """
        self.controller = controller
        self.runtime = runtime
        self.version_manager = version_manager
        
        # Track active graph executions
        self._active_graphs: Dict[str, Any] = {}
        
        logger.info("GraphAPI initialized")
    
    async def execute_graph(
        self,
        intent: str,
        mode: str = "react",
        env_context: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        POST /graphs/execute - Execute graph with intent.
        
        Args:
            intent: High-level goal description
            mode: Execution mode ("react" or "dag")
            env_context: Environment context
            config: Configuration overrides
            
        Returns:
            Dictionary with:
                - graph_id: Graph ID
                - status: Execution status
                - message: Status message
                
        Requirements: 26.7
        """
        try:
            from app.avatar.runtime.graph.controller.graph_controller import ExecutionMode
            
            # Convert mode string to enum
            exec_mode = ExecutionMode.REACT if mode == "react" else ExecutionMode.DAG
            
            # Execute graph
            result = await self.controller.execute(
                intent=intent,
                mode=exec_mode,
                env_context=env_context or {},
                config=config or {},
            )
            
            # Extract graph_id from result (if available)
            graph_id = getattr(result, 'graph_id', None) or 'unknown'
            
            return {
                'graph_id': graph_id,
                'status': result.final_status,
                'success': result.success,
                'completed_nodes': result.completed_nodes,
                'failed_nodes': result.failed_nodes,
                'skipped_nodes': result.skipped_nodes,
                'execution_time': result.execution_time,
                'error_message': result.error_message,
            }
            
        except Exception as e:
            logger.error(f"Error executing graph: {e}", exc_info=True)
            return {
                'graph_id': None,
                'status': 'error',
                'success': False,
                'error_message': str(e),
            }
    
    async def get_graph(self, graph_id: str) -> Dict[str, Any]:
        """
        GET /graphs/{graph_id} - Get graph state.
        
        Args:
            graph_id: Graph ID
            
        Returns:
            Dictionary with graph state
        """
        try:
            # Get graph from active graphs or storage
            graph = self._active_graphs.get(graph_id)
            
            if not graph:
                return {
                    'graph_id': graph_id,
                    'error': 'Graph not found',
                }
            
            return {
                'graph_id': graph.id,
                'goal': graph.goal,
                'status': graph.status,
                'nodes': {
                    node_id: {
                        'id': node.id,
                        'capability_name': node.capability_name,
                        'status': node.status.value,
                        'outputs': node.outputs,
                        'error_message': node.error_message,
                    }
                    for node_id, node in graph.nodes.items()
                },
                'edges': {
                    edge_id: {
                        'source_node': edge.source_node,
                        'source_field': edge.source_field,
                        'target_node': edge.target_node,
                        'target_param': edge.target_param,
                    }
                    for edge_id, edge in graph.edges.items()
                },
                'created_at': graph.created_at.isoformat() if hasattr(graph, 'created_at') else None,
                'updated_at': graph.updated_at.isoformat() if hasattr(graph, 'updated_at') else None,
            }
            
        except Exception as e:
            logger.error(f"Error getting graph {graph_id}: {e}", exc_info=True)
            return {
                'graph_id': graph_id,
                'error': str(e),
            }
    
    async def get_graph_status(self, graph_id: str) -> Dict[str, Any]:
        """
        GET /graphs/{graph_id}/status - Get execution status.
        
        Args:
            graph_id: Graph ID
            
        Returns:
            Dictionary with execution status
        """
        try:
            graph = self._active_graphs.get(graph_id)
            
            if not graph:
                return {
                    'graph_id': graph_id,
                    'error': 'Graph not found',
                }
            
            # Count node statuses
            from app.avatar.runtime.graph.models.step_node import NodeStatus
            
            status_counts = {
                'pending': 0,
                'running': 0,
                'success': 0,
                'failed': 0,
                'skipped': 0,
            }
            
            for node in graph.nodes.values():
                status = node.status.value
                if status in status_counts:
                    status_counts[status] += 1
            
            return {
                'graph_id': graph_id,
                'status': graph.status,
                'total_nodes': len(graph.nodes),
                'node_status_counts': status_counts,
                'is_terminal': all(node.is_terminal() for node in graph.nodes.values()),
            }
            
        except Exception as e:
            logger.error(f"Error getting graph status {graph_id}: {e}", exc_info=True)
            return {
                'graph_id': graph_id,
                'error': str(e),
            }
    
    async def get_graph_cost(
        self,
        graph_id: str,
        context: Any
    ) -> Dict[str, Any]:
        """
        GET /graphs/{graph_id}/cost - Get execution cost.
        
        Args:
            graph_id: Graph ID
            context: ExecutionContext
            
        Returns:
            Dictionary with cost information
            
        Requirements: 32.6
        """
        try:
            graph = self._active_graphs.get(graph_id)
            
            if not graph:
                return {
                    'graph_id': graph_id,
                    'error': 'Graph not found',
                }
            
            # Get cost from runtime
            total_cost = self.runtime.get_execution_cost(graph, context)
            
            # Get per-node costs
            node_costs = {}
            for node_id, node in graph.nodes.items():
                if node.metadata and 'execution_cost' in node.metadata:
                    node_costs[node_id] = {
                        'cost': node.metadata['execution_cost'],
                        'latency': node.metadata.get('execution_latency', 0),
                    }
            
            return {
                'graph_id': graph_id,
                'total_cost': total_cost,
                'node_costs': node_costs,
                'currency': 'USD',
            }
            
        except Exception as e:
            logger.error(f"Error getting graph cost {graph_id}: {e}", exc_info=True)
            return {
                'graph_id': graph_id,
                'error': str(e),
            }
    
    async def get_graph_versions(self, graph_id: str) -> Dict[str, Any]:
        """
        GET /graphs/{graph_id}/versions - Get version history.
        
        Args:
            graph_id: Graph ID
            
        Returns:
            Dictionary with version history
            
        Requirements: 33.8
        """
        try:
            if not self.version_manager:
                return {
                    'graph_id': graph_id,
                    'error': 'Version manager not available',
                }
            
            # Get version history
            versions = self.version_manager.get_version_history(graph_id)
            
            return {
                'graph_id': graph_id,
                'total_versions': len(versions),
                'versions': [
                    {
                        'version': v.version,
                        'created_at': v.created_at.isoformat(),
                        'created_by': v.created_by,
                        'patch_applied': v.patch_applied is not None,
                    }
                    for v in versions
                ],
            }
            
        except Exception as e:
            logger.error(f"Error getting graph versions {graph_id}: {e}", exc_info=True)
            return {
                'graph_id': graph_id,
                'error': str(e),
            }
    
    async def pause_graph(self, graph_id: str) -> Dict[str, Any]:
        """
        POST /graphs/{graph_id}/pause - Pause execution.
        
        Args:
            graph_id: Graph ID
            
        Returns:
            Dictionary with operation result
        """
        try:
            # TODO: Implement pause functionality
            logger.warning(f"Pause not yet implemented for graph {graph_id}")
            
            return {
                'graph_id': graph_id,
                'status': 'not_implemented',
                'message': 'Pause functionality not yet implemented',
            }
            
        except Exception as e:
            logger.error(f"Error pausing graph {graph_id}: {e}", exc_info=True)
            return {
                'graph_id': graph_id,
                'error': str(e),
            }
    
    async def resume_graph(self, graph_id: str) -> Dict[str, Any]:
        """
        POST /graphs/{graph_id}/resume - Resume execution.
        
        Args:
            graph_id: Graph ID
            
        Returns:
            Dictionary with operation result
        """
        try:
            # TODO: Implement resume functionality
            logger.warning(f"Resume not yet implemented for graph {graph_id}")
            
            return {
                'graph_id': graph_id,
                'status': 'not_implemented',
                'message': 'Resume functionality not yet implemented',
            }
            
        except Exception as e:
            logger.error(f"Error resuming graph {graph_id}: {e}", exc_info=True)
            return {
                'graph_id': graph_id,
                'error': str(e),
            }
    
    async def cancel_graph(self, graph_id: str) -> Dict[str, Any]:
        """
        POST /graphs/{graph_id}/cancel - Cancel execution.
        
        Args:
            graph_id: Graph ID
            
        Returns:
            Dictionary with operation result
        """
        try:
            # TODO: Implement cancel functionality
            logger.warning(f"Cancel not yet implemented for graph {graph_id}")
            
            return {
                'graph_id': graph_id,
                'status': 'not_implemented',
                'message': 'Cancel functionality not yet implemented',
            }
            
        except Exception as e:
            logger.error(f"Error cancelling graph {graph_id}: {e}", exc_info=True)
            return {
                'graph_id': graph_id,
                'error': str(e),
            }
    
    def register_graph(self, graph: Any) -> None:
        """
        Register a graph for tracking.
        
        Args:
            graph: ExecutionGraph instance
        """
        self._active_graphs[graph.id] = graph
        logger.debug(f"Registered graph {graph.id}")
    
    def unregister_graph(self, graph_id: str) -> None:
        """
        Unregister a graph.
        
        Args:
            graph_id: Graph ID
        """
        if graph_id in self._active_graphs:
            del self._active_graphs[graph_id]
            logger.debug(f"Unregistered graph {graph_id}")
