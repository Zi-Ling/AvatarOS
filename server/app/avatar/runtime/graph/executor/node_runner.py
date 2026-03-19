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
        action_plane_proxy: Optional[Any] = None,
    ):
        self.executor = executor
        self.workspace = workspace
        self.artifact_collector = artifact_collector
        self.trace_store = trace_store
        # Optional ActionPlane proxy for governance-wrapped execution (Req 8.1, 8.6)
        self._action_plane_proxy = action_plane_proxy
        # Recovery policy engine for intelligent retry/escalation decisions
        from app.avatar.runtime.graph.managers.recovery_policy_engine import RecoveryPolicyEngine
        self._recovery_engine = RecoveryPolicyEngine()
        logger.info("NodeRunner initialized")
    
    def _persist_step_start(self, node: 'StepNode', run_id: str, step_index: int) -> Optional[str]:
        """在 DB 创建 Step 记录，返回 step_id（失败时静默，不影响执行）"""
        try:
            from app.db.task.task import Step
            from app.db.database import engine
            from sqlmodel import Session
            from datetime import datetime, timezone
            step = Step(
                run_id=run_id,
                step_index=step_index,
                step_name=node.id,
                skill_name=node.capability_name or "",
                input_params=node.params or {},
                status="running",
                started_at=datetime.now(timezone.utc),
            )
            with Session(engine) as session:
                session.add(step)
                session.commit()
                session.refresh(step)
                return step.id
        except Exception as e:
            logger.debug(f"[NodeRunner] Step DB persist start failed for {node.id}: {e}")
            return None

    def _persist_step_end(self, step_id: str, status: str, output_result=None, error_message: str = None):
        """更新 DB Step 状态（失败时静默）"""
        if not step_id:
            return
        try:
            from app.db.task.task import Step
            from app.db.database import engine
            from app.db.serialization import serialize_for_db
            from sqlmodel import Session
            from datetime import datetime, timezone
            with Session(engine) as session:
                step = session.get(Step, step_id)
                if step:
                    step.status = status
                    step.finished_at = datetime.now(timezone.utc)
                    if output_result:
                        # 只存非二进制的关键字段，避免 base64 图片撑爆 DB
                        safe = {
                            k: v for k, v in (output_result if isinstance(output_result, dict) else {}).items()
                            if k not in ("__artifacts__",) and not (isinstance(v, str) and len(v) > 4096)
                        }
                        step.output_result = serialize_for_db(safe) if safe else None
                    if error_message:
                        step.error_message = error_message[:2000]
                    session.add(step)
                    session.commit()
        except Exception as e:
            logger.debug(f"[NodeRunner] Step DB persist end failed for {step_id}: {e}")

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
        # Prefer exec_session_id (ExecutionSession UUID) for trace correlation,
        # fallback to identity.session_id, then "default".
        session_id = (
            (context.env.get("exec_session_id") if isinstance(getattr(context, "env", None), dict) else None)
            or getattr(getattr(context, "identity", None), "session_id", None)
            or "default"
        )
        workspace = getattr(context, "workspace", None) or self.workspace

        # --- DB Step 持久化（节点开始）---
        run_id = getattr(context, "_env", {}).get("run_id") if hasattr(context, "_env") else None
        step_index = list(graph.nodes.keys()).index(node.id) if node.id in graph.nodes else 0
        db_step_id = self._persist_step_start(node, run_id, step_index) if run_id else None

        # --- workspace snapshot（执行前）---
        before_snapshot: Dict[str, float] = {}
        if workspace:
            before_snapshot = workspace.snapshot_workspace()

        # Main execution loop with retry logic
        while True:
            try:
                # --- Event Trace: sandbox_start ---
                if self.trace_store:
                    try:
                        self.trace_store.record_event(
                            session_id=session_id,
                            event_type="sandbox_start",
                            step_id=node.id,
                            payload={"attempt": node.retry_count + 1, "capability": node.capability_name},
                        )
                    except Exception:
                        pass

                await self.executor.execute_node(graph, node, context)

                execution_time = (datetime.now() - start_time).total_seconds()

                # --- Event Trace: sandbox_end ---
                if self.trace_store:
                    try:
                        self.trace_store.record_event(
                            session_id=session_id,
                            event_type="sandbox_end",
                            step_id=node.id,
                            payload={"execution_time_s": execution_time, "status": "success"},
                        )
                    except Exception:
                        pass

                # --- artifact collection（执行后）---
                artifact_ids: List[str] = []
                if workspace and self.artifact_collector:
                    try:
                        export_to = None
                        try:
                            from app.core.workspace.manager import get_current_workspace
                            export_to = get_current_workspace()
                        except Exception:
                            export_to = self.executor._fallback_base_path
                        collected = await self.artifact_collector.collect(
                            workspace=workspace,
                            before_snapshot=before_snapshot,
                            node_id=node.id,
                            session_id=session_id,
                            export_to=export_to,
                        )
                        artifact_ids = [a.artifact_id for a in collected]
                        if artifact_ids:
                            # 把 artifact_ids 和文件路径挂到 node outputs
                            if node.outputs is None:
                                node.outputs = {}
                            node.outputs["__artifacts__"] = artifact_ids
                            node.outputs["__artifact_paths__"] = [
                                a.local_path for a in collected if a.local_path
                            ]
                            context.set_node_output(node.id, node.outputs)
                            logger.info(
                                f"[NodeRunner] Node {node.id} produced "
                                f"{len(artifact_ids)} artifact(s)"
                            )
                            # --- Event Trace: artifact_collected（每个 artifact 一条）---
                            if self.trace_store:
                                for ca in collected:
                                    try:
                                        self.trace_store.record_event(
                                            session_id=session_id,
                                            event_type="artifact_collected",
                                            step_id=node.id,
                                            artifact_id=ca.artifact_id,
                                            payload={
                                                "filename": ca.filename,
                                                "size": ca.size,
                                                "artifact_type": ca.artifact_type,
                                                "mime_type": ca.mime_type,
                                            },
                                        )
                                    except Exception:
                                        pass
                    except Exception as e:
                        logger.warning(
                            f"[NodeRunner] Artifact collection failed for node {node.id}: {e}"
                        )

                # --- 记录 artifact 消费关系（当前 node 消费了哪些 artifact）---
                self._record_artifact_consumption(node, session_id)

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
                    output_summary=self._summarize(
                        {k: v for k, v in (node.outputs or {}).items() if k != "__artifacts__"}
                    ),
                    workspace_path=str(workspace.root) if workspace else None,
                )

                # --- DB Step 持久化（节点成功）---
                self._persist_step_end(db_step_id, "completed", output_result=node.outputs)

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

                # Classify error and generate PlanningHint
                _error_classification = None
                try:
                    from app.avatar.runtime.graph.types.error_classification import ErrorClassifier
                    from app.avatar.runtime.graph.types.planning_hint import PlanningHint
                    _classifier = ErrorClassifier()
                    _error_classification = _classifier.classify(e)
                    _hint = PlanningHint(
                        error_class=_error_classification.error_class.value,
                        error_code=_error_classification.error_code.value,
                        suggested_fix=f"Error in node {node.id}: {error_message[:200]}",
                    )
                    # Inject into env_context
                    if hasattr(context, 'env') and isinstance(context.env, dict):
                        hints = context.env.setdefault("planning_hints", [])
                        hints.append({
                            "error_class": _hint.error_class,
                            "error_code": _hint.error_code,
                            "suggested_fix": _hint.suggested_fix,
                            "node_id": node.id,
                        })
                    # Emit debug event
                    try:
                        from app.avatar.runtime.observability.debug_event_stream import get_debug_event_stream
                        import time as _time_mod
                        get_debug_event_stream().emit(
                            "created", "ErrorClassification",
                            f"err_{node.id}_{int(_time_mod.time() * 1000)}",
                            f"class={_error_classification.error_class.value}, code={_error_classification.error_code.value}",
                        )
                    except Exception:
                        pass
                except Exception as _clf_err:
                    logger.debug("[NodeRunner] ErrorClassifier failed: %s", _clf_err)

                should_retry = node.retry_count < node.retry_policy.max_retries

                # 不可重试错误（如 4xx HTTP）直接跳过重试
                from app.avatar.runtime.graph.executor.graph_executor import ExecutionError
                if isinstance(e, ExecutionError) and not e.retryable:
                    should_retry = False

                # Consult RecoveryPolicyEngine for intelligent retry decisions
                if should_retry:
                    try:
                        # Prefer ErrorClassification-based decision if available
                        if _error_classification is not None:
                            _decision_result = self._recovery_engine.decide_from_classification(
                                _error_classification,
                                step_id=node.id,
                            )
                            if _decision_result.decision in ("fail_fast", "skip"):
                                logger.info(
                                    "[NodeRunner] RecoveryPolicy (classified): %s for %s "
                                    "(class=%s, code=%s)",
                                    _decision_result.decision, node.id,
                                    _decision_result.error_class.value,
                                    _decision_result.error_code.value,
                                )
                                should_retry = False
                            elif _decision_result.decision == "replan_subgraph":
                                logger.info(
                                    "[NodeRunner] RecoveryPolicy: replan_subgraph for %s",
                                    node.id,
                                )
                                should_retry = False
                        else:
                            # Fallback to legacy string-based recovery
                            from types import SimpleNamespace
                            _step_state = SimpleNamespace(
                                id=node.id,
                                status="failed",
                                retry_count=node.retry_count,
                                error_message=error_message,
                                input_snapshot_json=None,
                            )
                            _decision = self._recovery_engine.decide_step_recovery(
                                _step_state, max_retries=node.retry_policy.max_retries
                            )
                            if _decision == "escalate_to_replan":
                                logger.info(
                                    f"[NodeRunner] RecoveryPolicy: escalate_to_replan for {node.id} "
                                    f"(error: {error_message[:120]})"
                                )
                                should_retry = False
                    except Exception as _rpe:
                        logger.warning(f"[NodeRunner] RecoveryPolicyEngine failed: {_rpe}")

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

                    # --- Event Trace: retry_scheduled ---
                    if self.trace_store:
                        try:
                            self.trace_store.record_event(
                                session_id=session_id,
                                event_type="retry_scheduled",
                                step_id=node.id,
                                payload={
                                    "attempt": node.retry_count,
                                    "max_retries": node.retry_policy.max_retries,
                                    "delay_s": delay,
                                    "error": error_message,
                                },
                            )
                        except Exception:
                            pass

                    await asyncio.sleep(delay)
                    continue

                else:
                    node.mark_failed(error_message)
                    execution_time = (datetime.now() - start_time).total_seconds()

                    logger.error(
                        f"[NodeRunner] Node {node.id} failed permanently "
                        f"after {node.retry_count} retries in {execution_time:.2f}s: {error_message}"
                    )

                    # --- Event Trace: sandbox_broken（如果是 SandboxFailure）---
                    if self.trace_store:
                        try:
                            from app.avatar.runtime.executor.container_pool import SandboxFailure
                            is_sandbox_failure = isinstance(
                                getattr(e, "__cause__", None) or e,
                                SandboxFailure
                            )
                            if is_sandbox_failure:
                                self.trace_store.record_event(
                                    session_id=session_id,
                                    event_type="sandbox_broken",
                                    step_id=node.id,
                                    payload={"error": error_message, "retry_count": node.retry_count},
                                )
                        except Exception:
                            pass

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

                    # --- DB Step 持久化（节点失败）---
                    self._persist_step_end(db_step_id, "failed", error_message=error_message)

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
        container_id: Optional[str] = None,
        sandbox_backend: Optional[str] = None,
    ) -> None:
        """写一条 step trace，失败时静默（不影响主流程）"""
        if self.trace_store is None:
            return
        try:
            session_id = (
                (context.env.get("exec_session_id") if isinstance(getattr(context, "env", None), dict) else None)
                or getattr(getattr(context, "identity", None), "session_id", None)
                or "default"
            )
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
                container_id=container_id,
                sandbox_backend=sandbox_backend,
            )
        except Exception as e:
            logger.warning(f"[NodeRunner] Trace write failed for node {node.id}: {e}")

    def _record_artifact_consumption(self, node: 'StepNode', session_id: str) -> None:
        """
        记录当前 node 消费了哪些 artifact（通过 params 里的 artifact_id 引用）。
        扫描 node.params，找出值为 artifact_id 格式的字段，
        在 ArtifactRecord 里追加 consumed_by_step_ids。
        """
        try:
            import json as _json
            params = node.params or {}
            # 收集所有 param 值中看起来像 artifact_id 的字符串
            candidate_ids: List[str] = []
            for v in params.values():
                if isinstance(v, str) and len(v) == 36 and v.count("-") == 4:
                    candidate_ids.append(v)
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, str) and len(item) == 36 and item.count("-") == 4:
                            candidate_ids.append(item)

            if not candidate_ids:
                return

            from app.db.artifact_record import ArtifactRecord
            from app.db.database import engine
            from sqlmodel import Session as DBSession, select as db_select

            with DBSession(engine) as db:
                for aid in candidate_ids:
                    record = db.exec(
                        db_select(ArtifactRecord).where(ArtifactRecord.artifact_id == aid)
                    ).first()
                    if record:
                        existing = _json.loads(record.consumed_by_step_ids_json) if record.consumed_by_step_ids_json else []
                        if node.id not in existing:
                            existing.append(node.id)
                            record.consumed_by_step_ids_json = _json.dumps(existing)
                            db.add(record)
                db.commit()
        except Exception as e:
            logger.debug(f"[NodeRunner] _record_artifact_consumption failed for {node.id}: {e}")

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
