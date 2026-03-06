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
from typing import Dict, Any, Optional, List, TYPE_CHECKING
import logging
import asyncio
from datetime import datetime
from dataclasses import dataclass

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.graph.models.step_node import StepNode, NodeStatus
    from app.avatar.runtime.graph.context.execution_context import ExecutionContext
    from app.avatar.runtime.graph.executor.graph_executor import GraphExecutor
    from app.avatar.runtime.workspace.session_workspace import SessionWorkspace
    from app.avatar.runtime.workspace.artifact_collector import ArtifactCollector, CollectedArtifact
    from app.avatar.runtime.graph.storage.step_trace_store import StepTraceStore

logger = logging.getLogger(__name__)


@dataclass
class NodeResult:
    """
    Result of node execution.
    """
    success: bool
    outputs: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    execution_time: float = 0.0
    artifact_ids: List[str] = None  # artifact IDs produced by this node

    def __post_init__(self):
        if self.artifact_ids is None:
            self.artifact_ids = []


class NodeRunner:
    """
    Intermediate execution layer for graph nodes.
    
    NodeRunner provides clean separation of concerns:
    - GraphRuntime: Orchestration (scheduling, parallel execution, graph state)
    - NodeRunner: Node lifecycle (retry, streaming, status updates, artifact collection)
    - GraphExecutor: Capability execution (parameter resolution, execution)
    """
    
    def __init__(
        self,
        executor: 'GraphExecutor',
        workspace: Optional['SessionWorkspace'] = None,
        artifact_collector: Optional['ArtifactCollector'] = None,
        trace_store: Optional['StepTraceStore'] = None,
    ):
        self.executor = executor
        self.workspace = workspace
        self.artifact_collector = artifact_collector
        self.trace_store = trace_store
        logger.info("NodeRunner initialized")
    
    async def run_node(
        self,
        graph: 'ExecutionGraph',
        node: 'StepNode',
        context: 'ExecutionContext'
    ) -> NodeResult:
        """
        Execute a single node with retry logic, output storage, and artifact collection.
        """
        start_time = datetime.now()
        logger.info(f"[NodeRunner] Starting execution of node {node.id}")

        # Workspace is resolved once by GraphRuntime and stored on ExecutionContext.
        # NodeRunner has no global state dependency.
        session_id = getattr(context, "session_id", None) or "default"
        workspace = getattr(context, "workspace", None) or self.workspace

        # --- workspace snapshot（执行前）---
        before_snapshot: Dict[str, float] = {}
        if workspace:
            before_snapshot = workspace.snapshot_workspace()

        # Main execution loop with retry logic
        while True:
            try:
                await self.executor.execute_node(graph, node, context)

                execution_time = (datetime.now() - start_time).total_seconds()

                # --- artifact collection（执行后）---
                artifact_ids: List[str] = []
                if workspace and self.artifact_collector:
                    try:
                        export_to = None
                        try:
                            from app.core.workspace.manager import get_workspace_manager
                            export_to = get_workspace_manager().get_workspace()
                        except Exception:
                            if self.executor.base_path:
                                from pathlib import Path
                                export_to = Path(self.executor.base_path)
                        collected = await self.artifact_collector.collect(
                            workspace=workspace,
                            before_snapshot=before_snapshot,
                            node_id=node.id,
                            session_id=session_id,
                            export_to=export_to,
                        )
                        artifact_ids = [a.artifact_id for a in collected]
                        if artifact_ids:
                            # 把 artifact_ids 挂到 node outputs
                            if node.outputs is None:
                                node.outputs = {}
                            node.outputs["__artifacts__"] = artifact_ids
                            context.set_node_output(node.id, node.outputs)
                            logger.info(
                                f"[NodeRunner] Node {node.id} produced "
                                f"{len(artifact_ids)} artifact(s)"
                            )
                    except Exception as e:
                        logger.warning(
                            f"[NodeRunner] Artifact collection failed for node {node.id}: {e}"
                        )

                logger.info(
                    f"[NodeRunner] Node {node.id} completed successfully "
                    f"after {node.retry_count} retries in {execution_time:.2f}s"
                )

                # --- trace 记录 ---
                self._write_trace(
                    context=context,
                    node=node,
                    status="success",
                    started_at=start_time,
                    ended_at=datetime.now(),
                    execution_time_s=execution_time,
                    artifact_ids=artifact_ids,
                    output_summary=self._summarize(node.outputs),
                    workspace_path=str(workspace.root) if workspace else None,
                )

                return NodeResult(
                    success=True,
                    outputs=node.outputs,
                    retry_count=node.retry_count,
                    execution_time=execution_time,
                    artifact_ids=artifact_ids,
                )

            except Exception as e:
                error_message = str(e)
                logger.warning(
                    f"[NodeRunner] Node {node.id} failed (attempt {node.retry_count + 1}): {error_message}"
                )

                should_retry = node.retry_count < node.retry_policy.max_retries

                if should_retry:
                    node.retry_count += 1
                    delay = node.get_retry_delay()

                    logger.info(
                        f"[NodeRunner] Retrying node {node.id} "
                        f"(attempt {node.retry_count + 1}/{node.retry_policy.max_retries + 1}) "
                        f"after {delay:.2f}s delay"
                    )

                    node.add_stream_event(
                        "retry",
                        {"attempt": node.retry_count, "delay": delay, "error": error_message}
                    )
                    await asyncio.sleep(delay)
                    continue

                else:
                    node.mark_failed(error_message)
                    execution_time = (datetime.now() - start_time).total_seconds()

                    logger.error(
                        f"[NodeRunner] Node {node.id} failed permanently "
                        f"after {node.retry_count} retries in {execution_time:.2f}s: {error_message}"
                    )

                    # --- trace 记录 ---
                    self._write_trace(
                        context=context,
                        node=node,
                        status="failed",
                        started_at=start_time,
                        ended_at=datetime.now(),
                        execution_time_s=execution_time,
                        error_message=error_message,
                        workspace_path=str(workspace.root) if workspace else None,
                    )

                    return NodeResult(
                        success=False,
                        error_message=error_message,
                        retry_count=node.retry_count,
                        execution_time=execution_time,
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

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _write_trace(
        self,
        context: 'ExecutionContext',
        node: 'StepNode',
        status: str,
        started_at: datetime,
        ended_at: datetime,
        execution_time_s: float = 0.0,
        artifact_ids: Optional[List[str]] = None,
        error_message: Optional[str] = None,
        output_summary: Optional[str] = None,
        workspace_path: Optional[str] = None,
    ) -> None:
        """写一条 step trace，失败时静默（不影响主流程）"""
        if self.trace_store is None:
            return
        try:
            session_id = getattr(context, "session_id", None) or "default"
            graph_id   = getattr(context, "graph_id", None)

            self.trace_store.record_step(
                session_id=session_id,
                graph_id=graph_id,
                step_id=node.id,
                step_type=node.capability_name,
                status=status,
                started_at=started_at,
                ended_at=ended_at,
                execution_time_s=execution_time_s,
                retry_count=node.retry_count,
                error_message=error_message,
                workspace_path=workspace_path,
                artifact_ids=artifact_ids or [],
                output_summary=output_summary,
            )
        except Exception as e:
            logger.warning(f"[NodeRunner] Trace write failed for node {node.id}: {e}")

    @staticmethod
    def _summarize(data: Optional[Dict[str, Any]], max_len: int = 200) -> Optional[str]:
        """把 outputs 转成简短摘要字符串"""
        if not data:
            return None
        try:
            import json
            s = json.dumps(data, default=str, ensure_ascii=False)
            return s[:max_len] + "..." if len(s) > max_len else s
        except Exception:
            return str(data)[:max_len]
