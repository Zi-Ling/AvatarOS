"""
NodeRunner - Intermediate Execution Layer

NodeRunner sits between GraphRuntime (orchestration) and Executor (capability execution).
It handles the complete lifecycle of a single node execution:
- Parameter resolution via DataEdge traversal
- Retry logic with exponential backoff
- Streaming output collection
- Status updates and metadata tracking
- Output storage in ExecutionContext

Requirements: 5.1, 5.2, 5.7, 9.1, 9.2, 9.3
"""

from __future__ import annotations
from typing import Dict, Any, Optional, TYPE_CHECKING
import logging
import asyncio
from datetime import datetime
from dataclasses import dataclass

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.graph.models.step_node import StepNode, NodeStatus
    from app.avatar.runtime.graph.context.execution_context import ExecutionContext
    from app.avatar.runtime.graph.executor.graph_executor import GraphExecutor

logger = logging.getLogger(__name__)


@dataclass
class NodeResult:
    """
    Result of node execution.
    
    Attributes:
        success: Whether execution succeeded
        outputs: Node outputs (if successful)
        error_message: Error message (if failed)
        retry_count: Number of retries attempted
        execution_time: Total execution time in seconds
    """
    success: bool
    outputs: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    execution_time: float = 0.0


class NodeRunner:
    """
    Intermediate execution layer for graph nodes.
    
    NodeRunner provides clean separation of concerns:
    - GraphRuntime: Orchestration (scheduling, parallel execution, graph state)
    - NodeRunner: Node lifecycle (retry, streaming, status updates)
    - GraphExecutor: Capability execution (parameter resolution, execution)
    
    Requirements:
    - 5.1: Handle parameter resolution via DataEdge traversal
    - 5.2: Delegate to Executor for actual Capability execution
    - 5.7: Store outputs in ExecutionContext
    - 9.1: Handle retry logic with exponential backoff
    - 9.2: Calculate delay: initial_delay * (backoff_multiplier ^ retry_count)
    - 9.3: Increment retry_count in node metadata
    """
    
    def __init__(self, executor: 'GraphExecutor'):
        """
        Initialize NodeRunner.
        
        Args:
            executor: GraphExecutor for capability execution
        """
        self.executor = executor
        logger.info("NodeRunner initialized")
    
    async def run_node(
        self,
        graph: 'ExecutionGraph',
        node: 'StepNode',
        context: 'ExecutionContext'
    ) -> NodeResult:
        """
        Execute a single node with retry logic and output storage.
        
        This method:
        1. Attempts to execute the node
        2. Handles retries with exponential backoff on failure
        3. Collects streaming output events
        4. Updates node status and metadata
        5. Stores outputs in ExecutionContext
        
        Args:
            graph: ExecutionGraph containing the node
            node: StepNode to execute
            context: ExecutionContext for output storage
            
        Returns:
            NodeResult with execution outcome
            
        Requirements: 5.1, 5.2, 5.7, 9.1, 9.2, 9.3
        """
        start_time = datetime.now()
        logger.info(f"[NodeRunner] Starting execution of node {node.id}")
        
        # Main execution loop with retry logic
        while True:
            try:
                # Attempt execution (Requirement 5.1, 5.2)
                await self.executor.execute_node(graph, node, context)
                
                # If we get here, execution succeeded
                execution_time = (datetime.now() - start_time).total_seconds()
                
                # Note: Outputs already stored in ExecutionContext by GraphExecutor (Requirement 5.7)
                
                logger.info(
                    f"[NodeRunner] Node {node.id} completed successfully "
                    f"after {node.retry_count} retries in {execution_time:.2f}s"
                )
                
                return NodeResult(
                    success=True,
                    outputs=node.outputs,
                    retry_count=node.retry_count,
                    execution_time=execution_time
                )
                
            except Exception as e:
                # Execution failed
                error_message = str(e)
                logger.warning(
                    f"[NodeRunner] Node {node.id} failed (attempt {node.retry_count + 1}): {error_message}"
                )
                
                # Check if we should retry (before marking as failed)
                # Note: can_retry() checks if retry_count < max_retries
                should_retry = node.retry_count < node.retry_policy.max_retries
                
                if should_retry:
                    # Increment retry count (Requirement 9.3)
                    node.retry_count += 1
                    
                    # Calculate retry delay with exponential backoff (Requirement 9.2)
                    delay = node.get_retry_delay()
                    
                    logger.info(
                        f"[NodeRunner] Retrying node {node.id} "
                        f"(attempt {node.retry_count + 1}/{node.retry_policy.max_retries + 1}) "
                        f"after {delay:.2f}s delay"
                    )
                    
                    # Add retry event to stream
                    node.add_stream_event(
                        "retry",
                        {
                            "attempt": node.retry_count,
                            "delay": delay,
                            "error": error_message
                        }
                    )
                    
                    # Wait before retrying
                    await asyncio.sleep(delay)
                    
                    # Continue to next iteration (retry)
                    continue
                    
                else:
                    # Retries exhausted - mark as failed
                    node.mark_failed(error_message)
                    execution_time = (datetime.now() - start_time).total_seconds()
                    
                    logger.error(
                        f"[NodeRunner] Node {node.id} failed permanently "
                        f"after {node.retry_count} retries in {execution_time:.2f}s: {error_message}"
                    )
                    
                    return NodeResult(
                        success=False,
                        error_message=error_message,
                        retry_count=node.retry_count,
                        execution_time=execution_time
                    )
    
    async def run_node_with_streaming(
        self,
        graph: 'ExecutionGraph',
        node: 'StepNode',
        context: 'ExecutionContext',
        stream_callback: Optional[callable] = None
    ) -> NodeResult:
        """
        Execute a node with streaming output collection.
        
        This is an enhanced version of run_node() that supports real-time
        streaming of execution events (stdout, stderr, progress, etc.).
        
        Args:
            graph: ExecutionGraph containing the node
            node: StepNode to execute
            context: ExecutionContext for output storage
            stream_callback: Optional callback for streaming events
            
        Returns:
            NodeResult with execution outcome
            
        Requirements: 5.1, 5.2, 5.7, 9.1, 9.2, 9.3
        """
        # For now, this is the same as run_node()
        # Streaming support will be added when we integrate with actual skill execution
        result = await self.run_node(graph, node, context)
        
        # If callback provided, send all collected stream events
        if stream_callback and node.stream_events:
            for event in node.stream_events:
                try:
                    stream_callback(event)
                except Exception as e:
                    logger.warning(
                        f"[NodeRunner] Stream callback failed for node {node.id}: {e}"
                    )
        
        return result
    
    def run_node_sync(
        self,
        graph: 'ExecutionGraph',
        node: 'StepNode',
        context: 'ExecutionContext'
    ) -> NodeResult:
        """
        Synchronous wrapper for run_node().
        
        This is a convenience method for non-async contexts.
        
        Args:
            graph: ExecutionGraph containing the node
            node: StepNode to execute
            context: ExecutionContext for output storage
            
        Returns:
            NodeResult with execution outcome
        """
        # Create event loop if needed
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # Run async method
        return loop.run_until_complete(self.run_node(graph, node, context))
    
    async def run_nodes_parallel(
        self,
        graph: 'ExecutionGraph',
        nodes: list['StepNode'],
        context: 'ExecutionContext',
        max_concurrent: Optional[int] = None
    ) -> list[NodeResult]:
        """
        Execute multiple nodes in parallel with concurrency limit.
        
        This is a helper method for GraphRuntime to execute ready nodes in parallel.
        
        Args:
            graph: ExecutionGraph containing the nodes
            nodes: List of StepNodes to execute
            context: ExecutionContext for output storage
            max_concurrent: Optional limit on concurrent executions
            
        Returns:
            List of NodeResults in same order as input nodes
        """
        if not nodes:
            return []
        
        logger.info(
            f"[NodeRunner] Executing {len(nodes)} nodes in parallel "
            f"(max_concurrent: {max_concurrent or 'unlimited'})"
        )
        
        # If no concurrency limit, execute all at once
        if max_concurrent is None or max_concurrent >= len(nodes):
            tasks = [self.run_node(graph, node, context) for node in nodes]
            results = await asyncio.gather(*tasks, return_exceptions=False)
            return results
        
        # Otherwise, use semaphore to limit concurrency
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def run_with_semaphore(node: 'StepNode') -> NodeResult:
            async with semaphore:
                return await self.run_node(graph, node, context)
        
        tasks = [run_with_semaphore(node) for node in nodes]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        
        return results
