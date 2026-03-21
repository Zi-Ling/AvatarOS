"""
GraphRuntime - Core Graph Execution Engine

GraphRuntime orchestrates the execution of ExecutionGraphs using:
- Scheduler for ready node detection
- NodeRunner for node execution
- Parallel execution with asyncio
- Failure propagation
- Event emission via EventBus

Requirements: 3.1, 3.2, 3.3, 3.7, 4.3, 11.1, 11.2, 11.6, 11.7
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, TYPE_CHECKING
import logging
import asyncio
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.graph.models.step_node import StepNode, NodeStatus
    from app.avatar.runtime.graph.context.execution_context import ExecutionContext
    from app.avatar.runtime.graph.scheduler.scheduler import Scheduler
    from app.avatar.runtime.graph.executor.node_runner import NodeRunner
    from app.avatar.runtime.events.bus import EventBus

logger = logging.getLogger(__name__)


class ExecutionMode(str, Enum):
    """Graph execution mode"""
    COMPLETE = "complete"  # Execute entire graph (DAG mode)
    INCREMENTAL = "incremental"  # Execute ready nodes only (ReAct mode)


@dataclass
class ExecutionResult:
    """
    Result of graph execution.
    
    Attributes:
        success: Whether execution completed successfully
        final_status: Final graph status
        completed_nodes: Number of nodes completed
        failed_nodes: Number of nodes failed
        skipped_nodes: Number of nodes skipped
        execution_time: Total execution time in seconds
        error_message: Error message if execution failed
        is_stuck: Whether execution is stuck (no ready nodes but pending nodes exist)
        graph: The ExecutionGraph after execution (for node output access)
    """
    success: bool
    final_status: str
    completed_nodes: int = 0
    failed_nodes: int = 0
    skipped_nodes: int = 0
    execution_time: float = 0.0
    error_message: Optional[str] = None
    is_stuck: bool = False
    graph: Optional[Any] = None  # ExecutionGraph, typed as Any to avoid circular import
    summary: Optional[str] = None  # Human-readable result summary from AnswerSynthesizer


class GraphRuntime:
    """
    Core graph execution engine.
    
    GraphRuntime orchestrates graph execution by:
    1. Using Scheduler to identify ready nodes
    2. Executing ready nodes in parallel via NodeRunner
    3. Propagating failures to downstream nodes
    4. Emitting events via EventBus
    5. Managing graph state transitions
    6. Tracking execution cost and enforcing budgets
    
    Requirements:
    - 3.1: Execute graphs with parallel node execution
    - 3.2: Update graph state after each execution cycle
    - 3.3: Support incremental execution (ReAct mode)
    - 3.7: Emit events for graph lifecycle
    - 4.3: Use Scheduler for ready node detection
    - 11.1: Propagate failures to downstream nodes
    - 11.2: Mark downstream nodes as SKIPPED
    - 11.6: Use outgoing_edges adjacency index
    - 11.7: Handle optional dependencies correctly
    - 32.6: Expose get_execution_cost API
    - 32.11: Emit cost metrics
    - 32.12: Log cost information
    - 32.13: Track accumulated cost
    """
    
    def __init__(
            self,
            scheduler: 'Scheduler',
            node_runner: 'NodeRunner',
            context: Optional['ExecutionContext'] = None,
            event_bus: Optional['EventBus'] = None,
            config: Optional[Dict[str, Any]] = None
        ):
            """
            Initialize GraphRuntime.

            Args:
                scheduler: Scheduler for ready node detection
                node_runner: NodeRunner for node execution
                context: Optional default ExecutionContext (can be overridden per execution)
                event_bus: Optional EventBus for event emission
                config: Optional configuration dict with runtime settings

            Requirements: 29.8, 29.9, 29.10
            """
            self.scheduler = scheduler
            self.node_runner = node_runner
            self.default_context = context
            self.event_bus = event_bus
            self.config = config or {}

            logger.info("GraphRuntime initialized")


    
    async def execute_graph(
        self,
        graph: 'ExecutionGraph',
        context: Optional['ExecutionContext'] = None,
        mode: ExecutionMode = ExecutionMode.COMPLETE,
        max_nodes: Optional[int] = None,
        max_edges: Optional[int] = None,
        max_execution_time: Optional[float] = None
    ) -> ExecutionResult:
        """
        Execute an execution graph.
        
        This is the main entry point for graph execution. It runs the execution
        loop until the graph reaches a terminal state or resource limits are exceeded.
        
        Creates an ExecutionContext at the start if not provided (Requirement 29.8).
        
        Args:
            graph: ExecutionGraph to execute
            context: Optional ExecutionContext for runtime data (creates new if None)
            mode: Execution mode (COMPLETE or INCREMENTAL)
            max_nodes: Maximum number of nodes allowed (optional)
            max_edges: Maximum number of edges allowed (optional)
            max_execution_time: Maximum execution time in seconds (optional)
            
        Returns:
            ExecutionResult with execution outcome
            
        Requirements: 3.1, 3.2, 3.3, 3.6, 17.1, 17.2, 17.3, 17.4, 29.8
        """
        start_time = datetime.now()
        
        # Use default context if not provided, or create new one (Requirement 29.8, 29.9)
        if context is None:
            if self.default_context is not None:
                context = self.default_context
                logger.info(f"[GraphRuntime] Using default ExecutionContext for graph {graph.id}")
            else:
                from app.avatar.runtime.graph.context.execution_context import ExecutionContext
                # Resolve session workspace so NodeRunner doesn't need global lookups
                _session_id = graph.metadata.get('session_id')
                _workspace = None
                if _session_id:
                    try:
                        from app.avatar.runtime.workspace import get_session_workspace_manager
                        _ws_mgr = get_session_workspace_manager()
                        if _ws_mgr is not None:
                            _workspace = _ws_mgr.get_or_create(_session_id)
                    except Exception:
                        pass
                context = ExecutionContext(
                    graph_id=graph.id,
                    goal_desc=graph.goal,
                    inputs=graph.metadata.get('inputs', {}),
                    session_id=_session_id,
                    task_id=graph.id,
                    env=graph.metadata.get('env', {}),
                    workspace=_workspace,
                )
                logger.info(f"[GraphRuntime] Created ExecutionContext for graph {graph.id}")
        
        # Use config defaults if parameters not provided (Requirement 29.10)
        if max_execution_time is None:
            max_execution_time = self.config.get('max_execution_time')
        if max_nodes is None:
            max_nodes = self.config.get('max_nodes')
        if max_edges is None:
            max_edges = self.config.get('max_edges')
        
        logger.info(
            f"[GraphRuntime] Starting graph execution: {graph.id} "
            f"(mode: {mode.value}, nodes: {len(graph.nodes)})"
        )
        
        # Enforce resource limits before execution (Requirement 17.1, 17.2, 3.6)
        limit_error = self._check_resource_limits(graph, max_nodes, max_edges)
        if limit_error:
            logger.error(f"[GraphRuntime] Resource limit exceeded: {limit_error}")
            return ExecutionResult(
                success=False,
                final_status="failed",
                execution_time=0.0,
                error_message=limit_error
            )
        
        # Emit graph started event
        self._emit_event("graph_started", {"graph_id": graph.id, "mode": mode.value})
        
        try:
            # Main execution loop
            while not self._is_terminal(graph):
                # Check execution time limit (Requirement 17.3, 17.4)
                if max_execution_time:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    if elapsed > max_execution_time:
                        error_msg = (
                            f"Execution time limit exceeded: {elapsed:.2f}s > {max_execution_time}s"
                        )
                        logger.error(f"[GraphRuntime] {error_msg}")
                        
                        # Mark graph as failed and store error
                        graph.status = "failed"
                        graph.metadata['error'] = error_msg
                        
                        return ExecutionResult(
                            success=False,
                            final_status="failed",
                            execution_time=elapsed,
                            error_message=error_msg
                        )
                
                # Get ready nodes from scheduler (Requirement 4.3)
                ready_nodes = self.scheduler.get_ready_nodes(graph)
                
                if not ready_nodes:
                    # No ready nodes but graph not terminal - deadlock or waiting
                    # Propagate any failures before exiting (Requirement 11.1, 11.2)
                    self._propagate_failures(graph)
                    
                    logger.warning(
                        f"[GraphRuntime] No ready nodes found but graph not terminal. "
                        f"This may indicate a deadlock or missing dependencies."
                    )
                    # Mark as stuck for incremental mode
                    if mode == ExecutionMode.INCREMENTAL:
                        execution_time = (datetime.now() - start_time).total_seconds()
                        result = self._compute_execution_result(graph, execution_time, is_incremental=True)
                        result.is_stuck = True
                        return result
                    break
                
                logger.info(
                    f"[GraphRuntime] Executing {len(ready_nodes)} ready nodes in parallel"
                )
                
                # Execute ready nodes in parallel (Requirement 3.1)
                await self._execute_nodes_parallel(graph, ready_nodes, context)
                
                # Propagate failures to downstream nodes (Requirement 11.1, 11.2)
                self._propagate_failures(graph)
                
                # Update graph state (Requirement 3.2)
                graph.status = self._compute_graph_status(graph)
                
                # For incremental mode, stop after one cycle (Requirement 3.3)
                if mode == ExecutionMode.INCREMENTAL:
                    break
            
            # Update final graph status (in case loop didn't execute or after break)
            graph.status = self._compute_graph_status(graph)
            
            # Compute final result
            execution_time = (datetime.now() - start_time).total_seconds()
            result = self._compute_execution_result(
                graph, 
                execution_time, 
                is_incremental=(mode == ExecutionMode.INCREMENTAL)
            )
            result.graph = graph  # 附带 graph 供调用方读取节点输出
            
            # Check if graph is stuck (no ready nodes but not terminal)
            # Only mark as stuck if we're NOT in incremental mode (incremental mode handles this earlier)
            if mode != ExecutionMode.INCREMENTAL and not self._is_terminal(graph) and graph.status == "pending":
                result.is_stuck = True
            
            # Emit graph completed event
            self._emit_event(
                "graph_completed" if result.success else "graph_failed",
                {
                    "graph_id": graph.id,
                    "status": result.final_status,
                    "execution_time": execution_time,
                    "completed_nodes": result.completed_nodes,
                    "failed_nodes": result.failed_nodes
                }
            )
            
            logger.info(
                f"[GraphRuntime] Graph execution completed: {graph.id} "
                f"(status: {result.final_status}, time: {execution_time:.2f}s, "
                f"completed: {result.completed_nodes}, failed: {result.failed_nodes})"
            )
            
            return result
            
        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            error_message = f"Graph execution failed with exception: {str(e)}"
            
            logger.error(
                f"[GraphRuntime] {error_message}",
                exc_info=True
            )
            
            # Emit graph failed event
            self._emit_event(
                "graph_failed",
                {
                    "graph_id": graph.id,
                    "error": error_message,
                    "execution_time": execution_time
                }
            )
            
            return ExecutionResult(
                success=False,
                final_status="failed",
                execution_time=execution_time,
                error_message=error_message
            )
    
    async def execute_ready_nodes(
        self,
        graph: 'ExecutionGraph',
        context: Optional['ExecutionContext'] = None
    ) -> ExecutionResult:
        """
        Execute only the currently ready nodes (for ReAct mode).
        
        This is a convenience method that calls execute_graph with INCREMENTAL mode.
        Creates an ExecutionContext if not provided.
        
        Args:
            graph: ExecutionGraph to execute
            context: Optional ExecutionContext for runtime data (creates new if None)
            
        Returns:
            ExecutionResult with execution outcome
            
        Requirements: 3.3, 29.8
        """
        return await self.execute_graph(graph, context, mode=ExecutionMode.INCREMENTAL)
    
    async def _execute_nodes_parallel(
        self,
        graph: 'ExecutionGraph',
        nodes: List['StepNode'],
        context: 'ExecutionContext'
    ) -> None:
        """
        Execute multiple nodes in parallel using NodeRunner.
        
        Args:
            graph: ExecutionGraph containing the nodes
            nodes: List of ready nodes to execute
            context: ExecutionContext for runtime data
            
        Requirements: 3.1, 4.3
        """
        if not nodes:
            return
        
        # Emit node started events
        for node in nodes:
            self._emit_event(
                "node_started",
                {
                    "graph_id": graph.id,
                    "node_id": node.id,
                    "capability": node.capability_name,
                    "description": (node.metadata or {}).get("description", ""),
                }
            )
        
        # Execute nodes in parallel using NodeRunner
        results = await self.node_runner.run_nodes_parallel(
            graph, nodes, context, max_concurrent=self.scheduler.max_concurrent_nodes
        )
        
        # Emit node completed/failed events
        for node, result in zip(nodes, results):
            if result.success:
                self._emit_event(
                    "node_completed",
                    {
                        "graph_id": graph.id,
                        "node_id": node.id,
                        "execution_time": result.execution_time,
                        "retry_count": result.retry_count
                    }
                )
            else:
                self._emit_event(
                    "node_failed",
                    {
                        "graph_id": graph.id,
                        "node_id": node.id,
                        "error": result.error_message,
                        "retry_count": result.retry_count
                    }
                )
    
    def _propagate_failures(self, graph: 'ExecutionGraph') -> None:
        """
        Propagate failures to downstream nodes.
        
        When a node fails, all downstream nodes that depend on it (via required edges)
        should be marked as SKIPPED. Nodes with only optional failed dependencies
        should still execute.
        
        Args:
            graph: ExecutionGraph to process
            
        Requirements: 11.1, 11.2, 11.6, 11.7
        """
        from app.avatar.runtime.graph.models.step_node import NodeStatus
        
        # Log all node statuses for debugging
        logger.info(
            f"[GraphRuntime] _propagate_failures called. Node statuses: "
            f"{[(n.id, n.status.value) for n in graph.nodes.values()]}"
        )
        
        # Find all failed nodes
        failed_nodes = [
            node for node in graph.nodes.values()
            if node.status == NodeStatus.FAILED
        ]
        
        if not failed_nodes:
            logger.info("[GraphRuntime] No failed nodes found, skipping propagation")
            return
        
        logger.info(
            f"[GraphRuntime] Propagating failures from {len(failed_nodes)} failed nodes: "
            f"{[n.id for n in failed_nodes]}"
        )
        
        # For each failed node, mark downstream nodes as SKIPPED
        for failed_node in failed_nodes:
            self._mark_downstream_skipped(graph, failed_node)
    
    def _mark_downstream_skipped(
        self,
        graph: 'ExecutionGraph',
        failed_node: 'StepNode',
        _root_error: Optional[str] = None,
    ) -> None:
        """
        Mark downstream nodes as SKIPPED recursively with error context.
        
        Uses outgoing_edges adjacency index for efficient traversal.
        Propagates the root cause error message so downstream nodes and
        the planner know WHY they were skipped.
        
        Args:
            graph: ExecutionGraph containing the nodes
            failed_node: The failed node whose downstream should be skipped
            _root_error: Root cause error message (auto-extracted from failed_node if None)
            
        Requirements: 11.1, 11.2, 11.6, 11.7
        """
        from app.avatar.runtime.graph.models.step_node import NodeStatus
        
        # Extract root cause error from the failed node
        if _root_error is None:
            _root_error = getattr(failed_node, 'error_message', None) or "unknown error"
            # Truncate to avoid bloating metadata
            if len(_root_error) > 300:
                _root_error = _root_error[:300] + "..."
        
        # Get outgoing edges using adjacency index (Requirement 11.6)
        outgoing_edges = graph.get_outgoing_edges(failed_node.id)
        
        logger.info(
            f"[GraphRuntime] Checking downstream of {failed_node.id}, "
            f"found {len(outgoing_edges)} outgoing edges"
        )
        
        for edge in outgoing_edges:
            logger.info(f"[GraphRuntime] Processing edge {edge.id}")
            
            # Skip if edge is optional (Requirement 11.7)
            if edge.optional:
                logger.info(f"[GraphRuntime] Edge {edge.id} is optional, skipping")
                continue
            
            # Get target node
            target_node = graph.nodes.get(edge.target_node)
            logger.info(f"[GraphRuntime] Target node {edge.target_node}: status={target_node.status if target_node else 'N/A'}")
            if not target_node:
                logger.info(f"[GraphRuntime] Target node {edge.target_node} not found")
                continue
            
            # Skip if already in terminal state
            if target_node.is_terminal():
                logger.info(f"[GraphRuntime] Target node {target_node.id} is already terminal: {target_node.status}")
                continue
            
            # Mark as SKIPPED with error context (Requirement 11.2)
            skip_reason = (
                f"Required dependency {failed_node.id} failed: {_root_error}"
            )
            logger.info(f"[GraphRuntime] Marking node {target_node.id} as SKIPPED")
            target_node.mark_skipped(skip_reason)
            
            # Store structured error context in node metadata for planner access
            if not hasattr(target_node, 'metadata') or target_node.metadata is None:
                target_node.metadata = {}
            target_node.metadata['_skip_cause'] = {
                'failed_dependency': failed_node.id,
                'error_summary': _root_error,
            }
            
            logger.info(
                f"[GraphRuntime] Marked node {target_node.id} as SKIPPED "
                f"due to failed dependency {failed_node.id}"
            )
            
            # Recursively mark downstream nodes (pass root error through)
            self._mark_downstream_skipped(graph, target_node, _root_error=_root_error)
    
    def _is_terminal(self, graph: 'ExecutionGraph') -> bool:
        """
        Check if graph is in a terminal state.
        
        A graph is terminal when all nodes are in terminal states
        (SUCCESS, FAILED, SKIPPED, CANCELLED).
        
        Args:
            graph: ExecutionGraph to check
            
        Returns:
            True if graph is terminal, False otherwise
        """
        return all(node.is_terminal() for node in graph.nodes.values())
    
    def _compute_graph_status(self, graph: 'ExecutionGraph') -> str:
        """
        Compute current graph status based on node states.
        
        Args:
            graph: ExecutionGraph to analyze
            
        Returns:
            Graph status string
        """
        from app.avatar.runtime.graph.models.step_node import NodeStatus
        
        # Count node statuses
        status_counts = {}
        for node in graph.nodes.values():
            status = node.status.value
            status_counts[status] = status_counts.get(status, 0) + 1
        
        # Determine graph status
        if status_counts.get("running", 0) > 0:
            return "running"
        elif status_counts.get("failed", 0) > 0:
            return "failed"
        elif all(node.status == NodeStatus.SUCCESS for node in graph.nodes.values()):
            return "success"
        elif all(node.is_terminal() for node in graph.nodes.values()):
            # All terminal but not all success - partial success
            return "partial_success"
        else:
            return "pending"
    
    def _compute_execution_result(
        self,
        graph: 'ExecutionGraph',
        execution_time: float,
        is_incremental: bool = False
    ) -> ExecutionResult:
        """
        Compute final execution result from graph state.
        
        Args:
            graph: ExecutionGraph that was executed
            execution_time: Total execution time in seconds
            is_incremental: Whether this was an incremental execution
            
        Returns:
            ExecutionResult with statistics
        """
        from app.avatar.runtime.graph.models.step_node import NodeStatus
        
        # Count node statuses
        completed = sum(1 for n in graph.nodes.values() if n.status == NodeStatus.SUCCESS)
        failed = sum(1 for n in graph.nodes.values() if n.status == NodeStatus.FAILED)
        skipped = sum(1 for n in graph.nodes.values() if n.status == NodeStatus.SKIPPED)
        
        final_status = self._compute_graph_status(graph)
        
        # For incremental mode, success means no failures (even if status is pending)
        # For complete mode, success means final status is success or partial_success
        if is_incremental:
            success = failed == 0
        else:
            success = final_status in ("success", "partial_success")
        
        return ExecutionResult(
            success=success,
            final_status=final_status,
            completed_nodes=completed,
            failed_nodes=failed,
            skipped_nodes=skipped,
            execution_time=execution_time
        )
    
    def _emit_event(self, event_type: str, data: Dict) -> None:
        """
        Emit an event via EventBus if available.
        node_started / node_completed / node_failed 同时映射为前端可识别的
        step.start / step.end / step.failed 事件，实现实时进度推送。
        """
        if self.event_bus:
            try:
                from app.avatar.runtime.events.types import Event, EventType
                et = EventType(event_type)
                event = Event(
                    type=et,
                    source="graph_runtime",
                    payload=data
                )
                self.event_bus.publish(event)

                # 映射 node 事件 → 前端 step 事件
                _NODE_TO_STEP = {
                    "node_started":   EventType.STEP_START,
                    "node_completed": EventType.STEP_END,
                    "node_failed":    EventType.STEP_FAILED,
                }
                if event_type in _NODE_TO_STEP:
                    node_id = data.get("node_id", "")
                    step_payload = {
                        "session_id":  data.get("session_id", ""),
                        "skill_name":  data.get("capability", ""),
                        "description": data.get("description", ""),
                        "status":      "running" if event_type == "node_started" else (
                                       "failed"    if event_type == "node_failed" else "completed"),
                        "raw_output":  data.get("outputs"),
                        "error":       data.get("error"),
                    }
                    step_event = Event(
                        type=_NODE_TO_STEP[event_type],
                        source="graph_runtime",
                        payload=step_payload,
                        step_id=str(node_id),
                    )
                    self.event_bus.publish(step_event)

            except Exception as e:
                logger.warning(f"[GraphRuntime] Failed to emit event {event_type}: {e}")
    
    def get_execution_cost(self, graph: 'ExecutionGraph', context: 'ExecutionContext') -> float:
        """
        Get total execution cost for a graph.
        
        This method retrieves the accumulated cost from the ExecutionContext,
        which is updated by the GraphExecutor after each node execution.
        
        Args:
            graph: ExecutionGraph to get cost for
            context: ExecutionContext containing accumulated cost
            
        Returns:
            Total execution cost in USD
            
        Requirements: 32.6, 32.13
        """
        # Get accumulated cost from context (Requirement 32.13)
        accumulated_cost = context.variables.get('accumulated_cost', 0.0)
        
        logger.debug(
            f"[GraphRuntime] Graph {graph.id} execution cost: ${accumulated_cost:.4f}"
        )
        
        # Emit cost metric (Requirement 32.11)
        self._emit_cost_metric(graph.id, accumulated_cost)
        
        # Log cost information (Requirement 32.12)
        logger.info(
            f"[GraphRuntime] Graph {graph.id} total cost: ${accumulated_cost:.4f} "
            f"({len(graph.nodes)} nodes)"
        )
        
        return accumulated_cost
    
    def _emit_cost_metric(self, graph_id: str, cost: float) -> None:
        """
        Emit cost metric for monitoring.
        
        Args:
            graph_id: ID of the graph
            cost: Total execution cost
            
        Requirements: 32.11
        """
        # Emit cost event
        self._emit_event(
            "graph_cost_calculated",
            {
                "graph_id": graph_id,
                "total_cost": cost,
                "timestamp": datetime.now().isoformat()
            }
        )
        
        # TODO: Emit Prometheus metric when observability layer is implemented
        # graph_execution_cost_total.labels(graph_id=graph_id).set(cost)
    
    def _check_resource_limits(
        self,
        graph: 'ExecutionGraph',
        max_nodes: Optional[int],
        max_edges: Optional[int]
    ) -> Optional[str]:
        """
        Check if graph exceeds resource limits.
        
        Args:
            graph: ExecutionGraph to check
            max_nodes: Maximum number of nodes allowed
            max_edges: Maximum number of edges allowed
            
        Returns:
            Error message if limits exceeded, None otherwise
            
        Requirements: 17.1, 17.2, 3.6
        """
        # Check node limit (Requirement 17.1)
        if max_nodes and len(graph.nodes) > max_nodes:
            return (
                f"Graph exceeds maximum node limit: "
                f"{len(graph.nodes)} > {max_nodes}"
            )
        
        # Check edge limit (Requirement 17.2)
        if max_edges and len(graph.edges) > max_edges:
            return (
                f"Graph exceeds maximum edge limit: "
                f"{len(graph.edges)} > {max_edges}"
            )
        
        return None


