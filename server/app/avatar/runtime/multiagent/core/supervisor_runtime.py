"""SupervisorRuntime — independent dispatch loop for multi-agent execution.

Replaces the one-shot layer-by-layer execution in _execute_multi_agent_mode
with a continuous loop: scan ready tasks → match worker → dispatch handoff →
collect results → update graph → retry/reroute → check termination.

All tunable parameters come from MultiAgentConfig (no hardcoding).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

from app.avatar.runtime.multiagent.roles.agent_instance import AgentInstance, AgentInstanceStatus, TaskPacket
from app.avatar.runtime.multiagent.config import MultiAgentConfig
from app.avatar.runtime.multiagent.core.handoff_envelope import HandoffEnvelope
from app.avatar.runtime.multiagent.resilience.health_monitor import AgentHealthMonitor, HealthStatus
from app.avatar.runtime.multiagent.resilience.repair_loop import RepairLoop, RepairAction
from app.avatar.runtime.multiagent.core.subtask_graph import SubtaskGraph, SubtaskNode
from app.avatar.runtime.multiagent.observability.trace_integration import TraceIntegration
from app.avatar.runtime.multiagent.execution.worker_pool import WorkerPoolManager

logger = logging.getLogger(__name__)


# ── Dispatch result ─────────────────────────────────────────────────

@dataclass
class TaskResult:
    """Result of a single subtask execution."""
    node_id: str
    success: bool
    result_data: Dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    execution_time: float = 0.0
    worker_instance_id: str = ""
    # Worker-initiated feedback: suggestions, quality signals, retry hints
    feedback: Optional[Dict[str, Any]] = None


@dataclass
class RuntimeResult:
    """Aggregate result of the full dispatch loop."""
    success: bool
    completed_nodes: int = 0
    failed_nodes: int = 0
    total_nodes: int = 0
    execution_time: float = 0.0
    subtask_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    handoff_envelopes: Dict[str, HandoffEnvelope] = field(default_factory=dict)
    terminated_reason: str = ""



# ── Worker wrapper ──────────────────────────────────────────────────

class WorkerInstance:
    """Wraps an AgentInstance with dispatch-loop bookkeeping.

    Tracks retry counts, assignment history, and provides the bridge
    between SupervisorRuntime and the real AgentInstance lifecycle
    (spawn → activate → complete_task / mark_failed → idle/terminate).
    """

    def __init__(self, agent: AgentInstance, config: MultiAgentConfig) -> None:
        self._agent = agent
        self._cfg = config
        self._retry_counts: Dict[str, int] = {}  # node_id → retries
        self._assigned_node: Optional[str] = None
        self._busy = False

    @property
    def agent(self) -> AgentInstance:
        return self._agent

    @property
    def instance_id(self) -> str:
        return self._agent.instance_id

    @property
    def role_name(self) -> str:
        return self._agent.role_name

    @property
    def is_busy(self) -> bool:
        return self._busy

    @property
    def assigned_node(self) -> Optional[str]:
        return self._assigned_node

    def can_retry(self, node_id: str) -> bool:
        return self._retry_counts.get(node_id, 0) < self._cfg.max_task_retries

    def record_attempt(self, node_id: str) -> int:
        count = self._retry_counts.get(node_id, 0) + 1
        self._retry_counts[node_id] = count
        return count

    def assign(self, node_id: str) -> None:
        self._busy = True
        self._assigned_node = node_id
        self._agent.activate(node_id)

    def release(self, node_id: str, success: bool) -> None:
        self._busy = False
        self._assigned_node = None
        if success:
            self._agent.complete_task(node_id)
        else:
            # Don't mark agent as failed — it can be reused
            if node_id in self._agent.state.owned_task_ids:
                self._agent.state.owned_task_ids.remove(node_id)
            if not self._agent.state.owned_task_ids:
                self._agent.state.status = AgentInstanceStatus.IDLE

    def terminate(self) -> None:
        self._agent.terminate()


# ── Subtask executor callback type ──────────────────────────────────

# The actual execution is delegated to a callback provided by the caller
# (typically GraphController). This keeps SupervisorRuntime decoupled
# from the execution engine.
SubtaskExecutor = Callable[
    [SubtaskNode, str, Dict[str, Any], Dict[str, Any], MultiAgentConfig],
    Coroutine[Any, Any, TaskResult],
]


# ── SupervisorRuntime ───────────────────────────────────────────────

class SupervisorRuntime:
    """Continuous dispatch loop for multi-agent subtask execution.

    Lifecycle:
        runtime = SupervisorRuntime(graph, config, ...)
        result = await runtime.run(executor_callback)

    The loop:
        while not terminated:
            1. Scan graph for ready nodes (deps satisfied, status=pending)
            2. Match each ready node to an available or new worker
            3. Dispatch via executor callback (creates real AgentInstance)
            4. Collect results, update graph
            5. Build HandoffEnvelopes for downstream
            6. On failure: retry same worker or reroute to new worker
            7. Check termination (all done / timeout / max rounds)
    """

    def __init__(
        self,
        graph: SubtaskGraph,
        config: MultiAgentConfig,
        instance_manager: Any,  # InstanceManager from supervisor.py
        trace: Optional[TraceIntegration] = None,
        max_rounds: int = 0,
        timeout_seconds: float = 0.0,
        health_monitor: Optional[AgentHealthMonitor] = None,
        repair_loop: Optional[RepairLoop] = None,
        worker_pool: Optional[WorkerPoolManager] = None,
        local_replanner: Optional[Any] = None,  # LocalReplannerProtocol
    ) -> None:
        self._graph = graph
        self._cfg = config
        self._instance_manager = instance_manager
        self._trace = trace or TraceIntegration()
        self._max_rounds = max_rounds or config.default_max_rounds
        self._timeout_seconds = timeout_seconds or config.default_timeout_seconds

        # P1: health / repair / pool (auto-create if config enables)
        self._health = health_monitor or (
            AgentHealthMonitor(config) if config.repair_enabled else None
        )
        self._repair = repair_loop or (
            RepairLoop(config, self._health) if config.repair_enabled else None
        )
        self._pool = worker_pool or WorkerPoolManager(config, self._health)
        # DecisionAdvisor: injected into RepairLoop if provided
        self._advisor = getattr(self._repair, '_advisor', None) if self._repair else None
        # Local re-planner for feedback-driven subgraph replacement
        self._local_replanner = local_replanner

        # Worker pool: instance_id → WorkerInstance
        self._workers: Dict[str, WorkerInstance] = {}
        # Per-node retry tracking (across workers)
        self._node_retries: Dict[str, int] = {}
        # Per-node feedback-triggered retry tracking
        self._feedback_retries: Dict[str, int] = {}
        # Results
        self._results: Dict[str, Dict[str, Any]] = {}
        self._handoffs: Dict[str, HandoffEnvelope] = {}
        # Concurrency
        self._semaphore = asyncio.Semaphore(config.max_concurrent_subtasks)
        # Termination
        self._terminated = False
        self._terminated_reason = ""
        self._round = 0

    @property
    def graph(self) -> SubtaskGraph:
        return self._graph

    @property
    def results(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._results)

    @property
    def workers(self) -> Dict[str, WorkerInstance]:
        return dict(self._workers)


    # ── Main dispatch loop ──────────────────────────────────────────

    async def run(self, executor: SubtaskExecutor) -> RuntimeResult:
        """Execute the streaming dispatch loop until termination.

        Unlike a batch gather approach, this loop fires tasks as
        ``asyncio.Task`` objects and re-scans for newly-ready nodes
        whenever *any* in-flight task completes.  This ensures that a
        writer node whose only upstream researcher finishes early can
        start immediately — without waiting for sibling researchers.
        """
        start_mono = time.monotonic()
        consecutive_empty = 0

        self._trace.multi_agent_started(
            self._graph.metadata.get("goal", ""), "supervisor_runtime",
        )

        # In-flight asyncio tasks: task → node_id
        in_flight: Dict[asyncio.Task, str] = {}
        # Event signalled whenever an in-flight task completes
        _any_done = asyncio.Event()

        def _on_task_done(t: asyncio.Task) -> None:
            """Callback attached to every dispatched asyncio.Task."""
            _any_done.set()

        while not self._terminated:
            self._round += 1

            # Termination: max rounds
            if self._round > self._max_rounds:
                self._terminated = True
                self._terminated_reason = f"max_rounds ({self._max_rounds})"
                break

            # Termination: timeout
            elapsed = time.monotonic() - start_mono
            if elapsed > self._timeout_seconds:
                self._terminated = True
                self._terminated_reason = f"timeout ({self._timeout_seconds}s)"
                break

            # ── Harvest completed in-flight tasks ───────────────────────
            done_tasks = [t for t in in_flight if t.done()]
            for t in done_tasks:
                nid = in_flight.pop(t)
                exc = t.exception() if not t.cancelled() else None
                if exc is not None:
                    node = self._graph.nodes.get(nid)
                    if node and node.status == "running":
                        logger.error(
                            "[SupervisorRuntime] Dispatch exception for %s: %s",
                            nid, exc,
                        )
                        self._graph.mark_failed(nid)
                        self._results[nid] = {
                            "success": False,
                            "error": str(exc),
                            "role": node.responsible_role,
                            "final_status": "failed",
                        }

            # Propagate failures after harvesting
            if done_tasks:
                self._propagate_failures()

            # ── Process pending local replan requests ───────────────────
            _replan_reqs = self._graph.metadata.pop("_replan_requests", [])
            for req in _replan_reqs:
                await self._handle_local_replan(req)

            # Termination: all nodes done
            if self._graph.all_completed():
                self._terminated = True
                self._terminated_reason = "all_completed"
                break

            # Check if any nodes are still actionable
            if self._all_terminal():
                self._terminated = True
                self._terminated_reason = "all_terminal"
                break

            # ── Scan and dispatch ready nodes ───────────────────────────
            ready = self._graph.get_ready_nodes()
            if not ready:
                if in_flight:
                    # Wait for any in-flight task to complete, then re-scan
                    _any_done.clear()
                    try:
                        remaining = self._timeout_seconds - (time.monotonic() - start_mono)
                        await asyncio.wait_for(
                            _any_done.wait(),
                            timeout=max(remaining, self._cfg.dispatch_event_min_wait),
                        )
                    except asyncio.TimeoutError:
                        pass
                    consecutive_empty = 0
                    continue

                consecutive_empty += 1
                if consecutive_empty >= self._cfg.dispatch_max_consecutive_empty:
                    self._terminated = True
                    self._terminated_reason = "no_ready_no_running"
                    break
                await asyncio.sleep(self._cfg.dispatch_poll_interval)
                continue

            consecutive_empty = 0

            # Fire each ready node as an independent asyncio.Task
            for node in ready:
                node.status = "running"
                t = asyncio.create_task(
                    self._dispatch_node(node, executor),
                    name=f"dispatch-{node.node_id}",
                )
                t.add_done_callback(_on_task_done)
                in_flight[t] = node.node_id

            # Yield control so newly-created tasks can start
            await asyncio.sleep(0)

        # ── Wait for any remaining in-flight tasks ──────────────────────
        if in_flight:
            remaining_tasks = list(in_flight.keys())
            done, _ = await asyncio.wait(
                remaining_tasks,
                timeout=max(
                    self._timeout_seconds - (time.monotonic() - start_mono),
                    self._cfg.dispatch_poll_interval,
                ),
            )
            for t in done:
                nid = in_flight.pop(t, None)
                exc = t.exception() if not t.cancelled() else None
                if exc is not None and nid:
                    node = self._graph.nodes.get(nid)
                    if node and node.status == "running":
                        self._graph.mark_failed(nid)
                        self._results[nid] = {
                            "success": False,
                            "error": str(exc),
                            "role": node.responsible_role,
                            "final_status": "failed",
                        }
            # Cancel any still-pending tasks
            for t in list(in_flight.keys()):
                t.cancel()
            self._propagate_failures()

        # Cleanup workers
        self._cleanup_all_workers()

        total_elapsed = time.monotonic() - start_mono
        completed = sum(
            1 for n in self._graph.nodes.values() if n.status == "completed"
        )
        failed = sum(
            1 for n in self._graph.nodes.values() if n.status == "failed"
        )

        self._trace.multi_agent_completed(
            self._graph.metadata.get("goal", ""),
            "success" if self._graph.all_completed() else "partial",
        )

        return RuntimeResult(
            success=self._graph.all_completed(),
            completed_nodes=completed,
            failed_nodes=failed,
            total_nodes=len(self._graph.nodes),
            execution_time=total_elapsed,
            subtask_results=dict(self._results),
            handoff_envelopes=dict(self._handoffs),
            terminated_reason=self._terminated_reason,
        )


    # ── Node dispatch ───────────────────────────────────────────────

    async def _dispatch_node(
        self,
        node: SubtaskNode,
        executor: SubtaskExecutor,
    ) -> None:
        """Dispatch a single node: acquire worker, execute, handle result."""
        async with self._semaphore:
            worker = self._acquire_worker(node.responsible_role, node.node_id)
            worker.assign(node.node_id)
            attempt = worker.record_attempt(node.node_id)

            self._trace.agent_task_assigned(
                worker.instance_id, node.responsible_role, node.node_id,
            )

            # Collect upstream context
            upstream = self._collect_upstream(node.node_id)

            try:
                task_result = await executor(
                    node,
                    worker.instance_id,
                    upstream,
                    self._results,
                    self._cfg,
                )

                if task_result.success:
                    self._handle_success(node, worker, task_result)
                else:
                    await self._handle_failure(
                        node, worker, task_result, executor,
                    )

            except Exception as exc:
                logger.error(
                    "[SupervisorRuntime] Node %s exception: %s",
                    node.node_id, exc,
                )
                fail_result = TaskResult(
                    node_id=node.node_id,
                    success=False,
                    error_message=str(exc),
                    worker_instance_id=worker.instance_id,
                )
                await self._handle_failure(
                    node, worker, fail_result, executor,
                )

    # ── Worker acquisition ──────────────────────────────────────────

    def _acquire_worker(self, role_name: str, task_id: str) -> WorkerInstance:
        """Find an idle worker for the role, or spawn a new one."""
        if self._cfg.worker_reuse_enabled:
            for w in self._workers.values():
                if (
                    w.role_name == role_name
                    and not w.is_busy
                    and w.agent.state.status != AgentInstanceStatus.TERMINATED
                    and not self._pool.is_quarantined(w.instance_id)
                    and not self._pool.is_draining(w.instance_id)
                ):
                    return w

        if not self._pool.can_spawn(role_name):
            raise RuntimeError(
                f"WorkerPool at capacity ({self._cfg.pool_max_workers}), "
                f"cannot spawn for role={role_name}"
            )

        # Spawn new via InstanceManager
        agent = self._instance_manager.spawn(role_name=role_name, task_id=task_id)
        if agent is None:
            raise RuntimeError(
                f"InstanceManager denied spawn for role={role_name}, task={task_id}"
            )
        worker = WorkerInstance(agent, self._cfg)
        self._workers[worker.instance_id] = worker

        # Register with pool and health monitor
        self._pool.register(worker.instance_id, role_name)
        if self._health:
            self._health.register(worker.instance_id, role_name)

        self._trace.agent_created(
            worker.instance_id, role_name,
        )
        return worker


    # ── Success handling ────────────────────────────────────────────

    def _handle_success(
        self,
        node: SubtaskNode,
        worker: WorkerInstance,
        task_result: TaskResult,
    ) -> None:
        """Handle successful task completion."""
        self._graph.mark_completed(node.node_id, task_result.result_data)
        worker.release(node.node_id, success=True)

        self._results[node.node_id] = {
            "success": True,
            "summary": task_result.result_data.get("summary", ""),
            "final_status": task_result.result_data.get("final_status", "completed"),
            "role": node.responsible_role,
            "artifact_paths": task_result.result_data.get("artifact_paths", []),
            "worker_instance_id": task_result.worker_instance_id,
            "feedback": task_result.feedback,
        }

        self._trace.agent_task_completed(
            worker.instance_id, node.responsible_role, node.node_id,
        )

        # P1: update health monitor
        if self._health:
            self._health.record_success(
                worker.instance_id,
                completion_time=task_result.execution_time,
            )

        # Build handoff envelopes for downstream
        self._build_handoffs(node, task_result)

        # Process worker feedback for dynamic adjudication
        if task_result.feedback and self._cfg.feedback_enabled:
            self._process_feedback(node, task_result)

    # ── Feedback-driven dynamic adjudication ───────────────────────

    def _process_feedback(
        self,
        node: SubtaskNode,
        task_result: TaskResult,
    ) -> None:
        """Evaluate worker feedback and optionally trigger re-execution or replan.

        Feedback schema (all fields optional):
            suggestion: str   — free-text suggestion from the worker
            action: str       — suggested action (RETRY_SEARCH, REPLAN_DOWNSTREAM, etc.)
            confidence: float — worker's confidence in the suggestion (0–1)
            context: dict     — additional context (e.g. alternative keywords)

        Actions:
            RETRY_SEARCH / RETRY_TASK → reset this node to pending for re-execution
            REPLAN_DOWNSTREAM → mark downstream pending nodes for local replan
            ABORT_DOWNSTREAM → mark downstream pending nodes as failed
            (anything else) → log only, no action
        """
        fb = task_result.feedback
        if not fb or not isinstance(fb, dict):
            return

        action = fb.get("action", "")
        confidence = fb.get("confidence", 0.0)
        suggestion = fb.get("suggestion", "")

        self._trace.agent_feedback(
            task_result.worker_instance_id,
            node.responsible_role,
            node.node_id,
            action=action,
            confidence=confidence,
            suggestion=suggestion[:self._cfg.intent_summary_max_chars],
        )

        # Gate: confidence too low
        if confidence < self._cfg.feedback_min_confidence:
            logger.debug(
                "[Feedback] Node %s feedback below threshold (%.2f < %.2f), ignoring",
                node.node_id, confidence, self._cfg.feedback_min_confidence,
            )
            return

        # Gate: action not in actionable set
        if action not in self._cfg.feedback_actionable_actions:
            logger.info(
                "[Feedback] Node %s action '%s' not actionable, logged only",
                node.node_id, action,
            )
            return

        # Gate: per-node feedback retry limit
        fb_count = self._feedback_retries.get(node.node_id, 0)
        if fb_count >= self._cfg.feedback_max_retries_per_node:
            logger.info(
                "[Feedback] Node %s feedback retry limit reached (%d), ignoring",
                node.node_id, fb_count,
            )
            return

        if action in ("RETRY_SEARCH", "RETRY_TASK"):
            # Undo the completion: reset node to pending for re-execution
            logger.info(
                "[Feedback] Node %s: worker suggests %s (confidence=%.2f): %s",
                node.node_id, action, confidence, suggestion,
            )
            node.status = "pending"
            node.result = None
            self._results.pop(node.node_id, None)
            self._feedback_retries[node.node_id] = fb_count + 1
            # Inject feedback context so the re-execution can use it
            if not node.result:
                node.result = {}
            node.result = {"_feedback_context": fb}

        elif action == "REPLAN_DOWNSTREAM":
            # Mark for local replan (改造点三 will handle the actual replan)
            logger.info(
                "[Feedback] Node %s: REPLAN_DOWNSTREAM (confidence=%.2f): %s",
                node.node_id, confidence, suggestion,
            )
            self._feedback_retries[node.node_id] = fb_count + 1
            # Store replan request for the dispatch loop to pick up
            self._graph.metadata.setdefault("_replan_requests", []).append({
                "trigger_node": node.node_id,
                "feedback": fb,
                "downstream_nodes": list(
                    self._graph.get_downstream_subgraph(node.node_id) - {node.node_id}
                ),
            })

        elif action == "ABORT_DOWNSTREAM":
            logger.warning(
                "[Feedback] Node %s: ABORT_DOWNSTREAM (confidence=%.2f): %s",
                node.node_id, confidence, suggestion,
            )
            downstream = self._graph.get_downstream_subgraph(node.node_id) - {node.node_id}
            for blocked_id in downstream:
                blocked = self._graph.nodes.get(blocked_id)
                if blocked and blocked.status == "pending":
                    blocked.status = "failed"
                    blocked.result = {
                        "error": f"aborted: upstream {node.node_id} feedback",
                        "_feedback": fb,
                    }
            self._feedback_retries[node.node_id] = fb_count + 1

    # ── Local re-planning ──────────────────────────────────────────

    async def _handle_local_replan(
        self,
        replan_request: Dict[str, Any],
    ) -> None:
        """Handle a local replan request triggered by worker feedback.

        Steps:
        1. Identify downstream pending nodes to replace
        2. If a LocalReplanner is available, call it to generate replacement nodes
        3. Hot-swap: remove old pending downstream nodes, insert new ones
        4. If no replanner, just reset downstream nodes to pending (simple retry)
        """
        trigger_node_id = replan_request.get("trigger_node", "")
        feedback = replan_request.get("feedback", {})
        downstream_ids = replan_request.get("downstream_nodes", [])

        if not downstream_ids:
            logger.debug("[LocalReplan] No downstream nodes to replan for %s", trigger_node_id)
            return

        # Filter to only pending/failed nodes (don't touch completed or running)
        replaceable = [
            nid for nid in downstream_ids
            if nid in self._graph.nodes
            and self._graph.nodes[nid].status in ("pending", "failed")
        ]

        if not replaceable:
            logger.debug("[LocalReplan] No replaceable downstream nodes for %s", trigger_node_id)
            return

        # Try LocalReplanner if available
        replanner = getattr(self, '_local_replanner', None)
        if replanner is not None:
            try:
                new_nodes = await replanner.replan(
                    trigger_node_id=trigger_node_id,
                    feedback=feedback,
                    current_graph=self._graph,
                    replaceable_node_ids=replaceable,
                    completed_results=self._results,
                )
                if new_nodes:
                    self._hot_swap_subgraph(replaceable, new_nodes)
                    self._trace._emit("multi_agent.local_replan", {
                        "trigger_node": trigger_node_id,
                        "replaced_nodes": replaceable,
                        "new_node_count": len(new_nodes),
                    })
                    logger.info(
                        "[LocalReplan] Replaced %d nodes with %d new nodes for %s",
                        len(replaceable), len(new_nodes), trigger_node_id,
                    )
                    return
            except Exception as exc:
                logger.warning("[LocalReplan] Replanner failed: %s, falling back to reset", exc)

        # Fallback: reset replaceable nodes to pending for simple re-execution
        for nid in replaceable:
            node = self._graph.nodes[nid]
            node.status = "pending"
            node.result = None
            self._results.pop(nid, None)

        self._trace._emit("multi_agent.local_replan_fallback", {
            "trigger_node": trigger_node_id,
            "reset_nodes": replaceable,
        })
        logger.info(
            "[LocalReplan] Fallback: reset %d downstream nodes to pending for %s",
            len(replaceable), trigger_node_id,
        )

    def _hot_swap_subgraph(
        self,
        old_node_ids: List[str],
        new_nodes: List[SubtaskNode],
    ) -> None:
        """Replace old nodes with new ones in the graph, preserving edges.

        - Removes old nodes and their internal edges
        - Adds new nodes
        - Re-wires: edges pointing TO old nodes now point to the first new node
        - Re-wires: edges FROM old nodes now come from the last new node
        - Adds sequential edges between new nodes
        """
        old_set = set(old_node_ids)

        # Collect edges that connect old nodes to the rest of the graph
        incoming_edges = [
            e for e in self._graph.edges
            if e.target_node_id in old_set and e.source_node_id not in old_set
        ]
        outgoing_edges = [
            e for e in self._graph.edges
            if e.source_node_id in old_set and e.target_node_id not in old_set
        ]

        # Remove old nodes and all their edges
        for nid in old_node_ids:
            self._graph.nodes.pop(nid, None)
        self._graph.edges = [
            e for e in self._graph.edges
            if e.source_node_id not in old_set and e.target_node_id not in old_set
        ]

        # Add new nodes
        for node in new_nodes:
            self._graph.nodes[node.node_id] = node

        if not new_nodes:
            return

        first_new = new_nodes[0].node_id
        last_new = new_nodes[-1].node_id

        # Re-wire incoming edges to first new node
        from app.avatar.runtime.multiagent.core.subtask_graph import SubtaskEdge
        for e in incoming_edges:
            self._graph.edges.append(SubtaskEdge(
                source_node_id=e.source_node_id,
                target_node_id=first_new,
                data_mapping=e.data_mapping,
            ))

        # Re-wire outgoing edges from last new node
        for e in outgoing_edges:
            self._graph.edges.append(SubtaskEdge(
                source_node_id=last_new,
                target_node_id=e.target_node_id,
                data_mapping=e.data_mapping,
            ))

        # Add sequential edges between new nodes
        for i in range(len(new_nodes) - 1):
            self._graph.edges.append(SubtaskEdge(
                source_node_id=new_nodes[i].node_id,
                target_node_id=new_nodes[i + 1].node_id,
            ))

    async def _handle_failure(
        self,
        node: SubtaskNode,
        worker: WorkerInstance,
        task_result: TaskResult,
        executor: SubtaskExecutor,
    ) -> None:
        """Handle task failure: use RepairLoop if available, else basic retry/reroute."""
        worker.release(node.node_id, success=False)

        # P1: update health monitor
        if self._health:
            status = self._health.record_failure(worker.instance_id)
            # Auto-quarantine broken workers
            if status == HealthStatus.BROKEN and self._pool.should_quarantine(worker.instance_id):
                self._pool.quarantine(
                    worker.instance_id,
                    reason=f"health={status.value}",
                )

        # P1: use RepairLoop for decision
        if self._repair:
            decision = self._repair.evaluate(
                node.node_id, worker.instance_id, task_result.error_message,
            )
            if decision is not None:
                if decision.action == RepairAction.RETRY_SAME:
                    node_retries = self._node_retries.get(node.node_id, 0)
                    backoff = min(
                        self._cfg.retry_backoff_base * (2 ** node_retries),
                        self._cfg.retry_backoff_max,
                    )
                    self._node_retries[node.node_id] = node_retries + 1
                    await asyncio.sleep(backoff)
                    node.status = "pending"
                    return
                elif decision.action == RepairAction.REROUTE:
                    self._node_retries[node.node_id] = self._node_retries.get(node.node_id, 0) + 1
                    node.status = "pending"
                    return
                else:
                    # split / review_first / replan — use local replan if available
                    self._node_retries[node.node_id] = self._node_retries.get(node.node_id, 0) + 1

                    if decision.action == RepairAction.REPLAN and self._local_replanner:
                        # Trigger local replan for this node's downstream
                        downstream = list(
                            self._graph.get_downstream_subgraph(node.node_id) - {node.node_id}
                        )
                        self._graph.metadata.setdefault("_replan_requests", []).append({
                            "trigger_node": node.node_id,
                            "feedback": {
                                "action": "REPLAN_DOWNSTREAM",
                                "suggestion": decision.reason,
                                "confidence": decision.metadata.get("confidence", 0.5),
                                "context": decision.metadata,
                            },
                            "downstream_nodes": downstream,
                        })
                        node.status = "pending"
                        logger.info(
                            "[RepairLoop] REPLAN queued for %s (%d downstream nodes)",
                            node.node_id, len(downstream),
                        )
                    else:
                        # split / review_first or replan without replanner: retry
                        logger.info(
                            "[RepairLoop] Action %s for %s (retrying)",
                            decision.action.value, node.node_id,
                        )
                        node.status = "pending"
                    return

        # Fallback: basic retry/reroute (when repair_enabled=False)
        node_retries = self._node_retries.get(node.node_id, 0)

        if node_retries < self._cfg.max_task_retries and worker.can_retry(node.node_id):
            self._node_retries[node.node_id] = node_retries + 1
            backoff = min(
                self._cfg.retry_backoff_base * (2 ** node_retries),
                self._cfg.retry_backoff_max,
            )
            await asyncio.sleep(backoff)
            node.status = "pending"
            return

        if self._cfg.reroute_on_failure and node_retries < self._cfg.max_task_retries:
            self._node_retries[node.node_id] = node_retries + 1
            node.status = "pending"
            return

        # Give up
        logger.warning(
            "[SupervisorRuntime] Node %s failed after %d attempts: %s",
            node.node_id, node_retries + 1, task_result.error_message,
        )
        self._graph.mark_failed(node.node_id)
        self._results[node.node_id] = {
            "success": False,
            "error": task_result.error_message,
            "role": node.responsible_role,
            "final_status": "failed",
            "worker_instance_id": task_result.worker_instance_id,
        }


    # ── Handoff envelope construction ───────────────────────────────

    def _build_handoffs(
        self,
        node: SubtaskNode,
        task_result: TaskResult,
    ) -> None:
        """Build HandoffEnvelopes for all downstream consumers."""
        downstream_edges = [
            e for e in self._graph.edges
            if e.source_node_id == node.node_id
        ]
        for edge in downstream_edges:
            target_node = self._graph.nodes.get(edge.target_node_id)
            target_role = target_node.responsible_role if target_node else ""

            envelope = HandoffEnvelope(
                source_role=node.responsible_role,
                source_instance_id=task_result.worker_instance_id,
                target_role=target_role,
                task_id=node.node_id,
                payload=task_result.result_data,
                artifact_refs=task_result.result_data.get("artifact_paths", []),
                context_summary=task_result.result_data.get("summary", ""),
                acceptance_checklist=node.success_criteria,
                confidence=1.0 if task_result.success else 0.0,
                status="delivered",
                feedback=task_result.feedback,
            )
            key = f"{node.node_id}->{edge.target_node_id}"
            self._handoffs[key] = envelope

            self._trace.agent_handoff(
                node.responsible_role, target_role, node.node_id,
            )

    # ── Upstream result collection ──────────────────────────────────

    def _collect_upstream(self, node_id: str) -> Dict[str, Any]:
        """Collect results from upstream nodes for a given node."""
        upstream: Dict[str, Any] = {}
        for edge in self._graph.edges:
            if edge.target_node_id == node_id:
                src = edge.source_node_id
                if src in self._results:
                    result = dict(self._results[src])
                    src_node = self._graph.nodes.get(src)
                    if src_node:
                        result["output_contract"] = src_node.output_contract
                    if edge.data_mapping:
                        result["data_bindings"] = edge.data_mapping
                    upstream[src] = result
        return upstream

    # ── Failure propagation ─────────────────────────────────────────

    def _propagate_failures(self) -> None:
        """Propagate failures from failed nodes to their downstream."""
        failed_ids = [
            nid for nid, n in self._graph.nodes.items()
            if n.status == "failed"
        ]
        for failed_id in failed_ids:
            downstream = self._graph.get_downstream_subgraph(failed_id) - {failed_id}
            newly_blocked: List[str] = []
            for blocked_id in downstream:
                blocked_node = self._graph.nodes.get(blocked_id)
                if blocked_node and blocked_node.status == "pending":
                    blocked_node.status = "failed"
                    blocked_node.result = {
                        "error": f"blocked: upstream {failed_id} failed",
                    }
                    newly_blocked.append(blocked_id)
            if newly_blocked:
                self._trace.failure_propagated(failed_id, newly_blocked)

    # ── Termination helpers ─────────────────────────────────────────

    def _all_terminal(self) -> bool:
        """Check if all nodes are in a terminal state (completed or failed)."""
        return all(
            n.status in ("completed", "failed")
            for n in self._graph.nodes.values()
        )

    def _cleanup_all_workers(self) -> None:
        """Terminate all workers at end of run."""
        for worker in self._workers.values():
            if worker.agent.state.status != AgentInstanceStatus.TERMINATED:
                worker.terminate()
                self._trace.agent_terminated(
                    worker.instance_id, worker.role_name,
                )
