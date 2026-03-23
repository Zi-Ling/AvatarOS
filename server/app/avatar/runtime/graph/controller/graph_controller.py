"""
GraphController - Orchestration layer for graph execution

Slim orchestrator that coordinates GraphPlanner, GraphRuntime, and helper modules:
- BudgetGuard: planner budget tracking and enforcement
- DedupGuard: intent-equivalent call deduplication
- GoalTracker: goal decomposition, coverage, terminal evidence, progress guard
- DagRepairHelper: DAG auto-repair
- EdgeManagerMixin: patch application, edge validation, implicit edges
- FanNodeExecutorMixin: FanOut/FanIn node execution
- EventEmitterMixin: plan.generated events, narrative helpers
- VerificationGateMixin: CompletionGate at FINISH decision points
- LongTaskMixin: long-task persistence, checkpoints, snapshots
- ReactFinishHandlerMixin: FINISH decision logic
- RecoveryHandlerMixin: truncation/schema/dedup recovery paths
- ReactPostExecutionMixin: post-node-execution processing
- ReactFinalizerMixin: finally-block cleanup

Supports ReAct mode (iterative) and DAG mode (one-shot).
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from enum import Enum
import logging
import asyncio

from app.avatar.runtime.graph.controller.budget_guard import BudgetGuard
from app.avatar.runtime.graph.controller.dedup_guard import DedupGuard
from app.avatar.runtime.graph.controller.goal_tracker import GoalTracker
from app.avatar.runtime.graph.controller.dag_repair import DagRepairHelper
from app.avatar.runtime.graph.controller.edge_manager import EdgeManagerMixin
from app.avatar.runtime.graph.controller.fan_node_executor import FanNodeExecutorMixin
from app.avatar.runtime.graph.controller.event_emitter import EventEmitterMixin
from app.avatar.runtime.graph.controller.verification_gate import VerificationGateMixin
from app.avatar.runtime.graph.controller.long_task_helpers import LongTaskContext, LongTaskMixin
from app.avatar.runtime.graph.controller.react_setup import ReactSetupMixin
from app.avatar.runtime.graph.controller.react_finish_handler import ReactFinishHandlerMixin
from app.avatar.runtime.graph.controller.recovery_handler import RecoveryHandlerMixin
from app.avatar.runtime.graph.controller.react_post_execution import ReactPostExecutionMixin
from app.avatar.runtime.graph.controller.react_finalizer import ReactFinalizerMixin
from app.avatar.runtime.graph.controller.react_state import ReactLoopState

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.graph.planner.graph_planner import GraphPlanner
    from app.avatar.runtime.graph.runtime.graph_runtime import GraphRuntime, ExecutionResult
    from app.avatar.runtime.graph.guard.planner_guard import PlannerGuard
    from app.avatar.runtime.graph.events.task_event_stream import TaskEventStream
    from app.avatar.evolution.pipeline import EvolutionPipeline

logger = logging.getLogger(__name__)


class ExecutionMode(str, Enum):
    """Graph execution mode"""
    REACT = "react"
    DAG = "dag"
    MULTI_AGENT = "multi_agent"


class GraphController(
    EdgeManagerMixin,
    FanNodeExecutorMixin,
    EventEmitterMixin,
    VerificationGateMixin,
    LongTaskMixin,
    ReactSetupMixin,
    ReactFinishHandlerMixin,
    RecoveryHandlerMixin,
    ReactPostExecutionMixin,
    ReactFinalizerMixin,
):
    """
    Orchestration layer for graph execution.

    Coordinates GraphPlanner, PlannerGuard, GraphRuntime, and helper modules.
    Supports ReAct (iterative) and DAG (one-shot) execution modes.
    """

    def __init__(
        self,
        planner: 'GraphPlanner',
        runtime: 'GraphRuntime',
        guard: Optional['PlannerGuard'] = None,
        max_concurrent_graphs: int = 10,
        max_planner_invocations_per_graph: int = 200,
        max_planner_tokens: Optional[int] = None,
        max_planner_calls: Optional[int] = None,
        max_planner_cost: Optional[float] = None,
        max_execution_cost: Optional[float] = None,
        evolution_pipeline: Optional['EvolutionPipeline'] = None,
        budget_account: Optional[Any] = None,
        task_def_engine: Optional[Any] = None,
        clarification_engine: Optional[Any] = None,
        complexity_analyzer: Optional[Any] = None,
        batch_plan_builder: Optional[Any] = None,
        phased_planner: Optional[Any] = None,
        collaboration_gate: Optional[Any] = None,
    ):
        self.planner = planner
        self.runtime = runtime
        self.guard = guard
        self.max_concurrent_graphs = max_concurrent_graphs
        self.max_planner_invocations_per_graph = max_planner_invocations_per_graph
        self.max_planner_tokens = max_planner_tokens
        self.max_planner_calls = max_planner_calls
        self.max_planner_cost = max_planner_cost
        self.max_execution_cost = max_execution_cost
        self._evolution_pipeline = evolution_pipeline
        self._budget_account = budget_account

        self._task_def_engine = task_def_engine
        self._clarification_engine = clarification_engine
        self._complexity_analyzer = complexity_analyzer
        self._batch_plan_builder = batch_plan_builder
        self._phased_planner = phased_planner
        self._collaboration_gate = collaboration_gate

        self._active_graphs: Dict[str, asyncio.Task] = {}
        self._graph_semaphore = asyncio.Semaphore(max_concurrent_graphs)

        self._budget = BudgetGuard(
            max_planner_tokens=max_planner_tokens,
            max_planner_calls=max_planner_calls,
            max_planner_cost=max_planner_cost,
        )
        self._dedup = DedupGuard()
        self._goal_tracker = GoalTracker()

        self._planner_usage = self._budget._usage

        logger.info(
            f"GraphController initialized: "
            f"max_concurrent_graphs={max_concurrent_graphs}, "
            f"max_planner_invocations={max_planner_invocations_per_graph}, "
            f"max_tokens={max_planner_tokens}, max_calls={max_planner_calls}, "
            f"max_cost={max_planner_cost}, max_execution_cost={max_execution_cost}"
        )

    @staticmethod
    def _make_error_result(graph: 'ExecutionGraph', error_message: str) -> 'ExecutionResult':
        from app.avatar.runtime.graph.runtime.graph_runtime import ExecutionResult
        return ExecutionResult(
            success=False,
            final_status="failed",
            error_message=error_message,
            graph=graph,
        )

    async def execute(
        self,
        intent: str,
        mode: ExecutionMode = ExecutionMode.REACT,
        env_context: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        control_handle: Optional[Any] = None,
    ) -> 'ExecutionResult':
        """Execute a graph from intent."""
        env_context = env_context or {}
        config = config or {}
        async with self._graph_semaphore:
            if mode == ExecutionMode.REACT:
                return await self._execute_react_mode(intent, env_context, config, control_handle)
            elif mode == ExecutionMode.DAG:
                return await self._execute_dag_mode(intent, env_context, config)
            elif mode == ExecutionMode.MULTI_AGENT:
                return await self._execute_multi_agent_mode(intent, env_context, config)
            else:
                raise ValueError(f"Unknown execution mode: {mode}")

    def get_planner_usage(self) -> Dict[str, Any]:
        """Get current planner usage statistics."""
        return self._budget.get_usage()

    # ── ReAct mode ──────────────────────────────────────────────────────

    async def _execute_react_mode(
        self,
        intent: str,
        env_context: Dict[str, Any],
        config: Dict[str, Any],
        control_handle: Optional[Any] = None,
    ) -> 'ExecutionResult':
        import time
        from app.avatar.runtime.graph.models.graph_patch import PatchOperation
        from app.avatar.runtime.graph.models.step_node import NodeStatus

        s = ReactLoopState(
            intent=intent,
            env_context=env_context,
            config=config,
            max_react_iterations=config.get('max_react_iterations', 200),
            max_graph_nodes=config.get('max_graph_nodes', 200),
            control_handle=control_handle,
        )

        # ── Depth-aware iteration limits ────────────────────────────────
        _depth = env_context.get("_execution_depth", 0)
        if _depth >= 2:
            s.max_react_iterations = min(
                s.max_react_iterations, self.DEEP_SUBTASK_MAX_ITERATIONS,
            )
            s.max_graph_nodes = min(s.max_graph_nodes, 30)
            logger.debug(
                "[GraphController] depth=%d → max_iterations=%d, max_nodes=%d",
                _depth, s.max_react_iterations, s.max_graph_nodes,
            )
        elif _depth == 1:
            # 子任务预算由父任务传递，同时设置迭代上限
            _budget_cap = env_context.get("_planner_budget")
            s.max_react_iterations = min(
                s.max_react_iterations, self.SUBTASK_MAX_ITERATIONS,
            )
            if _budget_cap is not None:
                s.max_react_iterations = min(s.max_react_iterations, int(_budget_cap))
            s.max_graph_nodes = min(s.max_graph_nodes, 80)

        # ── Setup: session, graph, workspace, goals, deliverables ───────
        _setup = await self._setup_react_session(intent, env_context, config)
        s.exec_session_id = _setup.exec_session_id
        s.lifecycle = _setup.lifecycle
        s.graph = _setup.graph
        s.shared_context = _setup.shared_context
        s.workspace = _setup.workspace
        s.session_id = _setup.session_id
        s.sub_goals = _setup.sub_goals
        s.deliverables = _setup.deliverables
        s.env_context = _setup.env_context

        # ── Task understanding layer (non-blocking) ────────────────────
        # Launch task understanding in background — don't block the first
        # Planner call. If Planner returns FINISH immediately (direct reply),
        # we skip task understanding entirely, saving ~10s of LLM latency.
        _task_understanding_task = asyncio.create_task(
            self._setup_task_understanding(intent, s.env_context, s.graph)
        )
        _task_understanding_resolved = False

        # ── Complexity-based routing ────────────────────────────────────
        # Deferred: will be checked after first Planner response if needed

        # ── Long-task runtime context ───────────────────────────────────
        s.lt_ctx = LongTaskContext.from_env(s.env_context)

        # ── NarrativeManager ────────────────────────────────────────────
        s.narrative_manager = self._setup_narrative_manager(
            s.session_id, s.exec_session_id, str(s.graph.id), intent, s.sub_goals
        )

        # ── Per-task state reset ────────────────────────────────────────
        self._budget.reset()
        self._planner_usage = self._budget._usage
        self._goal_tracker.reset()

        # ── Evolution trace ─────────────────────────────────────────────
        if self._evolution_pipeline:
            try:
                _evo_trace = self._evolution_pipeline._trace_collector.create_trace(
                    task_id=str(s.graph.id),
                    session_id=s.session_id or s.exec_session_id,
                    goal=intent,
                    task_type=s.env_context.get("task_type", "unknown"),
                )
                s.evo_trace_id = _evo_trace.trace_id
            except Exception as _evo_err:
                logger.debug(f"[GraphController] Evolution trace creation failed: {_evo_err}")

        try:
            while True:
                # ── Cancel / Pause check ────────────────────────────────
                _cancel = await self._check_cancellation_async(s)
                if _cancel is not None:
                    return _cancel

                # ── Hard limits check ───────────────────────────────────
                _limit = self._check_iteration_limits(s)
                if _limit is not None:
                    return _limit

                # ── Coverage hint injection ─────────────────────────────
                _coverage_summary = s.env_context.get("goal_coverage_summary")
                if _coverage_summary is not None:
                    try:
                        from app.avatar.runtime.verification.finish_bias_check import FinishBiasCheck
                        s.env_context = FinishBiasCheck().inject(s.env_context, _coverage_summary)
                    except Exception:
                        pass

                # ── Terminal evidence short-circuit ─────────────────────
                if s.planner_invocations > 0 and len(s.graph.nodes) > 0:
                    _te_reason = self._goal_tracker.check_terminal_evidence(
                        s.graph, s.sub_goals, s.env_context
                    )
                    if _te_reason:
                        logger.info(f"[TerminalEvidence] Short-circuit: {_te_reason}")
                        break

                # ── Plan ────────────────────────────────────────────────
                s.planner_invocations += 1
                logger.info(
                    f"Planner invocation {s.planner_invocations}/{self._budget.effective_max_calls}"
                )
                _plan_start = time.monotonic()
                try:
                    patch = await self.planner.plan_next_step(s.graph, s.env_context)
                except Exception as _plan_err:
                    _recovery = await self._handle_truncation_recovery(s, _plan_err)
                    if _recovery == "continue":
                        continue
                    elif _recovery == "abort":
                        return s.final_result
                    raise  # not a truncation error
                _plan_latency_ms = int((time.monotonic() - _plan_start) * 1000)

                # Clear stale recovery hints on successful plan
                self._clear_recovery_hints(s)

                self._budget.track(patch)
                _patch_meta = (patch.metadata or {}) if patch else {}

                is_finish = patch is None or (
                    len(patch.actions) == 1 and
                    patch.actions[0].operation == PatchOperation.FINISH
                )

                if not is_finish:
                    # Planner is doing actual work — reset FINISH rejection counter
                    s.consecutive_finish_rejections = 0
                    await s.lifecycle.on_plan_generated(
                        planner_input={"goal": intent, "graph_nodes": len(s.graph.nodes)},
                        planner_output={"actions": len(patch.actions)},
                        tokens_used=_patch_meta.get("tokens_used", 0),
                        cost_usd=_patch_meta.get("cost", 0.0),
                        latency_ms=_plan_latency_ms,
                    )

                # ── FINISH handling ─────────────────────────────────────
                if is_finish:
                    # Extract direct reply from Planner's final_message
                    _direct_msg = _patch_meta.get("final_message", "")
                    if _direct_msg:
                        s.direct_reply = _direct_msg

                    # If this is a direct reply (no nodes executed), skip gates
                    if _direct_msg and len(s.graph.nodes) == 0:
                        logger.info("[GraphController] Direct reply FINISH — skipping gates")
                        # Cancel background task understanding — not needed
                        if not _task_understanding_resolved:
                            _task_understanding_task.cancel()
                        break

                    _finish_action = await self._handle_finish_decision(s)
                    if _finish_action == "continue":
                        continue
                    elif _finish_action in ("break_partial", "break_failed", "break_uncertain"):
                        return s.final_result
                    # "break" or "break_pass" → fall through to break
                    break

                # ── Resolve deferred task understanding (first ADD_NODE) ──
                if not _task_understanding_resolved:
                    _task_understanding_resolved = True
                    try:
                        s.task_def, s.readiness, s.complexity, s.task_runtime_state = (
                            await _task_understanding_task
                        )
                    except asyncio.CancelledError:
                        pass
                    except Exception as _tu_err:
                        logger.warning(f"[GraphController] Deferred task understanding failed: {_tu_err}")

                    # Now check complexity routing (may redirect to DAG/phased)
                    _routed = await self._try_complexity_routing(s)
                    if _routed is not None:
                        return _routed

                # ── Guard validate ──────────────────────────────────────
                if self.guard:
                    validation = await self.guard.validate(patch, s.graph, context=s.env_context)
                    await s.lifecycle.on_policy_evaluated(
                        approved=validation.approved,
                        violations=validation.violations,
                        warnings=validation.warnings,
                        requires_approval=validation.requires_approval,
                    )
                    if not validation.approved:
                        s.error_message = f"Patch validation failed: {validation.violations}"
                        logger.error(s.error_message)
                        from app.avatar.runtime.graph.models.execution_graph import GraphStatus
                        s.graph.status = GraphStatus.FAILED
                        s.final_result = self._make_error_result(s.graph, error_message=s.error_message)
                        return s.final_result

                # ── Schema validation recovery ──────────────────────────
                _schema_action = await self._handle_schema_replan(s, patch)
                if _schema_action == "continue":
                    continue
                elif _schema_action == "abort":
                    return s.final_result

                # ── ClarificationGate ───────────────────────────────────
                if self._collaboration_gate is not None and s.task_def is not None:
                    try:
                        _clar_req = self._collaboration_gate.check_clarification_needed(patch, s.task_def)
                        if _clar_req is not None:
                            await self._collaboration_gate.suspend(_clar_req, s.env_context)
                    except Exception as _cg_err:
                        logger.debug(f"[ClarificationGate] Check skipped: {_cg_err}")

                # ── Dedup + Apply patch ─────────────────────────────────
                patch, _dedup_action = await self._handle_dedup_replan(s, patch)
                if _dedup_action == "continue":
                    continue
                elif _dedup_action == "break":
                    break

                self._apply_patch(patch, s.graph, lt_ctx=s.lt_ctx, env_context=s.env_context)
                self._emit_plan_generated(s.graph, s.env_context)

                # ── ParamBinder ─────────────────────────────────────────
                resolved_inputs = s.env_context.get("resolved_inputs")
                if resolved_inputs:
                    from app.avatar.runtime.context.param_binder import bind_params
                    for node in s.graph.nodes.values():
                        if node.status == NodeStatus.PENDING and node.params is not None:
                            bound, binding_log = bind_params(
                                skill_name=node.capability_name,
                                params=node.params,
                                resolved_inputs=resolved_inputs,
                            )
                            if binding_log:
                                node.params = bound
                                logger.info(
                                    f"[ParamBinder] {node.capability_name}: "
                                    f"bound {len(binding_log)} param(s)"
                                )

                await s.lifecycle.on_execution_started()

                # ── Real-time step.start for pending nodes ──────────────
                s.pending_node_ids = set()
                from app.avatar.runtime.narrative.models import TranslationContext as _TC
                for _n in s.graph.nodes.values():
                    if _n.status == NodeStatus.PENDING:
                        s.pending_node_ids.add(_n.id)
                        # Unified event source: emit via EventBus → SocketBridge
                        self._emit_step_start(_n, s.env_context)
                        try:
                            await s.narrative_manager.on_event(
                                "step.start",
                                step_id=str(_n.id),
                                context=_TC(
                                    skill_name=_n.capability_name,
                                    params_summary=self._summarize_params(_n.params),
                                    semantic_label=self._get_semantic_label(_n),
                                ),
                            )
                        except Exception as _ne:
                            logger.debug(f"[GraphController] Narrative step.start failed: {_ne}")

                # ── ApprovalGate check ──────────────────────────────────
                if self._collaboration_gate is not None and s.task_def is not None:
                    try:
                        from app.avatar.runtime.graph.models.step_node import NodeStatus as _NS
                        for _pn in s.graph.nodes.values():
                            if _pn.status == _NS.PENDING:
                                _approval_req = self._collaboration_gate.check_approval_needed(_pn, s.task_def)
                                if _approval_req is not None:
                                    await self._collaboration_gate.suspend(_approval_req, s.env_context)
                    except Exception as _ag_err:
                        logger.debug(f"[ApprovalGate] Check skipped: {_ag_err}")

                # ── Execute ready nodes (including FanOut/FanIn) ────────
                await self._execute_fan_nodes(s)
                result = await self.runtime.execute_ready_nodes(s.graph, context=s.shared_context)

                # ── Real-time step.end/step.failed via EventBus ─────────
                self._emit_realtime_step_events(s, s.env_context)

                # ── Post-execution processing ───────────────────────────
                await self._record_evolution_steps(s)

                # ── Apply recovery patch if NodeRunner generated one ────
                _recovery_patch = s.graph.metadata.get('_pending_recovery_patch') if hasattr(s.graph, 'metadata') and s.graph.metadata else None
                if _recovery_patch is not None:
                    _recovery_src = s.graph.metadata.pop('_recovery_source_node', '?')
                    s.graph.metadata.pop('_pending_recovery_patch', None)
                    logger.info(
                        "[GraphController] Applying recovery patch from node %s: %d actions",
                        _recovery_src, len(_recovery_patch.actions),
                    )
                    try:
                        repair_result = DagRepairHelper.auto_repair_dag(_recovery_patch)
                        if repair_result['repaired']:
                            _recovery_patch = repair_result['patch']
                        self._apply_patch(_recovery_patch, s.graph, env_context=s.env_context)
                    except Exception as _rp_err:
                        logger.warning("[GraphController] Recovery patch apply failed: %s", _rp_err)

                if s.lt_ctx is not None:
                    await self._lt_persist_step_results(s.graph, s.lt_ctx)

                await self._emit_step_narrative_events(s)

                # Long-task: routine checkpoint
                if s.lt_ctx is not None:
                    s.lt_ctx.step_count_since_checkpoint += 1
                    if s.lt_ctx.step_count_since_checkpoint >= s.lt_ctx.checkpoint_interval:
                        await self._lt_create_routine_checkpoint(s.lt_ctx)
                        s.lt_ctx.step_count_since_checkpoint = 0

                # Execution cost budget
                _cost_action = self._check_execution_cost(s)
                if _cost_action == "abort":
                    return s.final_result

                # BudgetAccount enforcement (session/task level)
                _ba_action = self._check_budget_account(s)
                if _ba_action == "abort":
                    return s.final_result

                # Circuit breaker
                _cb_action = self._check_circuit_breaker(s, result)
                if _cb_action == "abort":
                    return s.final_result

                # TaskRuntimeState + DeliverableState
                self._update_task_runtime_state(s)
                self._update_deliverable_states(s)

                # Progress guard
                _progress_issue = self._goal_tracker.check_progress(s.graph)
                if _progress_issue:
                    logger.warning(f"[ProgressGuard] {_progress_issue}")
                    break

                # SelfMonitor check (stuck/loop/budget detection)
                _force_terminate = await self._check_self_monitor(s)
                if _force_terminate:
                    logger.error(
                        "[SelfMonitor] Force-terminating ReAct loop — "
                        "task stuck with no progress"
                    )
                    s.lifecycle_status = "completed"
                    s.result_status = "partial_success"
                    s.error_message = (
                        "Task force-terminated: no meaningful progress detected "
                        "after multiple iterations. Returning partial results."
                    )
                    break

                # Uncovered sub-goals after success
                _uncov_action = self._check_uncovered_after_success(s, result)
                if _uncov_action == "continue":
                    continue

            # ── FINISH: compute final result ────────────────────────────
            s.final_result = self._compute_final_result(s, intent)
            return s.final_result

        finally:
            # Cancel background task understanding if still pending
            if not _task_understanding_resolved and not _task_understanding_task.done():
                _task_understanding_task.cancel()
            await self._finalize_react_session(s)

    # ── ReAct helper methods ────────────────────────────────────────────

    def _check_cancellation(self, s: ReactLoopState) -> Optional['ExecutionResult']:
        """Check cancel/pause signals. Returns error result if cancelled, else None."""
        _handle = s.control_handle
        if _handle is None:
            return None

        if _handle.is_cancelled():
            return self._cancel_graph(s, "Cancellation signal received")

        # Synchronous check — wait_if_paused is async but we handle it inline
        # in the main loop. This method only checks the immediate cancel flag.
        return None

    async def _check_cancellation_async(self, s: ReactLoopState) -> Optional['ExecutionResult']:
        """Async cancel/pause check with wait_if_paused support."""
        _handle = s.control_handle
        if _handle is None:
            return None

        if _handle.is_cancelled():
            return self._cancel_graph(s, "Cancellation signal received")

        await _handle.wait_if_paused()
        if _handle.is_cancelled():
            return self._cancel_graph(s, "Cancelled after resume")

        return None

    def _cancel_graph(self, s: ReactLoopState, reason: str) -> 'ExecutionResult':
        """Mark graph as cancelled and return error result."""
        logger.info(f"[GraphController] {reason}")
        from app.avatar.runtime.graph.models.execution_graph import GraphStatus
        s.graph.status = GraphStatus.FAILED
        s.lifecycle_status = "cancelled"
        s.result_status = "cancelled"
        s.error_message = "Task cancelled by user"
        if s.lt_ctx is not None:
            self._lt_save_snapshot(s.lt_ctx, s.graph, "pre_cancel")
        s.final_result = self._make_error_result(s.graph, error_message=s.error_message)
        return s.final_result

    def _check_iteration_limits(self, s: ReactLoopState) -> Optional['ExecutionResult']:
        """Check all hard iteration/budget limits. Returns error result if exceeded."""
        from app.avatar.runtime.graph.models.execution_graph import GraphStatus

        if s.planner_invocations >= self.max_planner_invocations_per_graph:
            s.error_message = f"Exceeded max planner invocations: {s.planner_invocations}"
            logger.error(s.error_message)
            s.graph.status = GraphStatus.FAILED
            s.final_result = self._make_error_result(s.graph, error_message=s.error_message)
            return s.final_result

        if s.planner_invocations >= s.max_react_iterations:
            s.error_message = f"Exceeded max ReAct iterations: {s.planner_invocations}"
            logger.error(s.error_message)
            s.graph.status = GraphStatus.FAILED
            s.final_result = self._make_error_result(s.graph, error_message=s.error_message)
            return s.final_result

        if len(s.graph.nodes) >= s.max_graph_nodes:
            s.error_message = f"Exceeded max graph nodes: {len(s.graph.nodes)}"
            logger.error(s.error_message)
            s.graph.status = GraphStatus.FAILED
            s.final_result = self._make_error_result(s.graph, error_message=s.error_message)
            return s.final_result

        budget_error = self._budget.check()
        if budget_error:
            s.error_message = f"Planner budget exceeded: {budget_error}"
            logger.error(f"[BudgetGuard] {s.error_message}")
            s.graph.status = GraphStatus.FAILED
            s.final_result = self._make_error_result(s.graph, error_message=s.error_message)
            return s.final_result

        return None

    @staticmethod
    def _clear_recovery_hints(s: ReactLoopState) -> None:
        """Clear stale recovery hints after a successful plan."""
        _keys = ("truncation_hint", "schema_violation_hint", "recovery_constraints")
        if any(k in s.env_context for k in _keys):
            s.env_context = dict(s.env_context)
            for k in _keys:
                s.env_context.pop(k, None)

    # Force-terminate after stuck threshold + this many extra ticks
    _STUCK_FORCE_TERMINATE_EXTRA = 3

    async def _check_self_monitor(self, s: ReactLoopState) -> bool:
        """Run SelfMonitor check as supplementary monitoring.

        Detects stuck loops, repeated actions, and budget warnings that
        ProgressGuard alone cannot catch.

        Returns True if the loop should be force-terminated due to
        prolonged stuck state (threshold + _STUCK_FORCE_TERMINATE_EXTRA).
        """
        try:
            from app.avatar.runtime.selfmonitor import SelfMonitor
            from app.avatar.runtime.kernel.monitor_context import MonitorContext
            from app.avatar.runtime.kernel.signals import SignalType

            # Lazily create a shared SelfMonitor instance
            if not hasattr(self, '_self_monitor'):
                self._self_monitor = SelfMonitor()

            from app.avatar.runtime.graph.models.step_node import NodeStatus
            completed = sum(
                1 for n in s.graph.nodes.values()
                if n.status == NodeStatus.SUCCESS
            )

            # Compute real delta from previous check
            delta = completed - s._prev_completed_count
            s._prev_completed_count = completed

            ctx = MonitorContext(
                task_id=str(s.graph.id),
                tick_count=s.planner_invocations,
                completed_items_count=completed,
                completed_items_delta=delta,
            )

            signals = self._self_monitor.check(ctx)
            for sig in signals:
                if sig.signal_type == SignalType.STUCK_ALERT:
                    ticks = sig.metadata.get("consecutive_ticks", 0)
                    threshold = sig.metadata.get("threshold", 10)
                    extra = ticks - threshold
                    logger.warning("[SelfMonitor] Stuck detected: %s", sig.reason)
                    if extra >= self._STUCK_FORCE_TERMINATE_EXTRA:
                        logger.error(
                            "[SelfMonitor] Force-terminating: stuck for "
                            "%d ticks beyond threshold (%d)",
                            extra, threshold,
                        )
                        return True
                    # Inject hint for Planner
                    s.env_context = dict(s.env_context)
                    s.env_context["self_monitor_hint"] = (
                        f"WARNING: No meaningful progress for {ticks} iterations. "
                        f"You MUST call FINISH now with current results."
                    )
                elif sig.signal_type == SignalType.LOOP_ALERT:
                    logger.warning("[SelfMonitor] Loop detected: %s", sig.reason)
                elif sig.signal_type == SignalType.BUDGET_WARNING:
                    logger.warning("[SelfMonitor] Budget warning: %s", sig.reason)
                elif sig.signal_type == SignalType.SHRINK_BUDGET:
                    logger.info("[SelfMonitor] Shrink budget: %s", sig.reason)
                    s.env_context = dict(s.env_context)
                    s.env_context["_budget_shrink_mode"] = True
        except Exception as _sm_err:
            logger.debug("[GraphController] SelfMonitor check skipped: %s", _sm_err)
        return False

    # ── Depth / Budget 常量 ───────────────────────────────────────────
    # depth=0 顶层: 允许 multi-agent + PhasedPlanner + BatchPlan
    # depth=1 子任务: 仅 react 迭代，禁止 multi-agent / PhasedPlanner
    # depth>=2 孙任务: 简单执行，max_iterations 大幅缩减
    MAX_EXECUTION_DEPTH = 2
    # 子任务 planner 预算占父剩余预算的比例
    CHILD_BUDGET_RATIO = 0.3
    # 子任务 planner 预算下限 / 上限
    CHILD_BUDGET_MIN = 10
    CHILD_BUDGET_MAX = 50
    # 深层子任务 (depth>=2) 的 react 迭代上限
    DEEP_SUBTASK_MAX_ITERATIONS = 15
    # 子任务 (depth=1) 的 react 迭代上限
    SUBTASK_MAX_ITERATIONS = 50

    async def _try_complexity_routing(self, s: ReactLoopState) -> Optional['ExecutionResult']:
        """Attempt complexity-based routing (batch/phased). Returns result if routed.

        Depth-aware: depth>=1 禁止 multi-agent 和 PhasedPlanner，
        只允许 react 内部多步迭代。
        """
        _depth = s.env_context.get("_execution_depth", 0)
        if _depth >= 1:
            logger.debug(
                "[GraphController] 跳过复杂度路由 (depth=%d, 仅允许 react)", _depth,
            )
            return None

        if s.complexity is None:
            return None

        # Observability: record whether routing was triggered
        _routing_triggered = False

        if s.complexity.task_type == "template_batch" and self._batch_plan_builder is not None:
            try:
                self._batch_plan_builder.build(s.complexity.batch_params, s.task_def)
                _routing_triggered = True
                self._record_routing_metadata(s, "template_batch", True)
                return await self._execute_dag_mode(s.intent, s.env_context, s.config)
            except Exception as _bpb_err:
                logger.warning(f"[GraphController] BatchPlanBuilder failed, falling back to ReAct: {_bpb_err}")

        if s.complexity.task_type == "complex" and self._phased_planner is not None:
            try:
                if self._phased_planner.should_activate(s.complexity, s.task_def, s.readiness, s.env_context):
                    _routing_triggered = True
                    self._record_routing_metadata(s, "phased_planner", True)
                    _goal_plan = await self._phased_planner.plan(s.complexity, s.intent, s.task_def)
                    _pp_env = dict(s.env_context)
                    try:
                        _pp_nm = self._setup_narrative_manager(
                            s.session_id, s.exec_session_id, str(s.graph.id), s.intent, s.sub_goals,
                        )
                        async def _phase_event_cb(event_type: str, step_id: str, description: str):
                            from app.avatar.runtime.narrative.models import TranslationContext as _TC
                            await _pp_nm.on_event(event_type, step_id, _TC(semantic_label=description))
                        _pp_env["_phase_event_callback"] = _phase_event_cb
                    except Exception:
                        pass
                    return await self._phased_planner.execute(_goal_plan, self, _pp_env, s.config)
            except Exception as _pp_err:
                logger.warning(f"[GraphController] PhasedPlanner failed, falling back to ReAct: {_pp_err}")

        if not _routing_triggered:
            self._record_routing_metadata(s, "react", False)

        return None

    @staticmethod
    def _record_routing_metadata(s: 'ReactLoopState', route: str, triggered: bool) -> None:
        """Record complexity routing decision in graph metadata for observability."""
        if hasattr(s.graph, 'metadata') and s.graph.metadata is not None:
            ca = s.graph.metadata.get("complexity_analysis", {})
            ca["routing_triggered"] = triggered
            ca["routed_to"] = route
            s.graph.metadata["complexity_analysis"] = ca

    async def _execute_fan_nodes(self, s: ReactLoopState) -> None:
        """Execute FanOut/FanIn nodes before regular execution."""
        from app.avatar.runtime.graph.models.step_node import NodeStatus
        try:
            from app.avatar.runtime.graph.models.step_node import NodeType as _NT
            for _fn in list(s.graph.nodes.values()):
                _node_type = getattr(_fn, "node_type", None)
                if _node_type == _NT.FAN_OUT and _fn.status == NodeStatus.PENDING:
                    await self._execute_fan_out_node(_fn, s.graph, s.shared_context)
                elif _node_type == _NT.FAN_IN and _fn.status == NodeStatus.PENDING:
                    _upstream_done = all(
                        s.graph.nodes.get(e.source_node) is not None and
                        s.graph.nodes[e.source_node].status in (NodeStatus.SUCCESS, NodeStatus.FAILED, NodeStatus.SKIPPED)
                        for e in s.graph.edges.values()
                        if e.target_node == _fn.id
                    )
                    if _upstream_done:
                        self._execute_fan_in_node(_fn, s.graph)
        except Exception as _fan_err:
            logger.debug(f"[FanOut/FanIn] Check skipped: {_fan_err}")

    def _compute_final_result(self, s: ReactLoopState, intent: str) -> 'ExecutionResult':
        """Compute the final ExecutionResult after the loop exits normally."""
        from app.avatar.runtime.graph.models.step_node import NodeStatus

        if s.lt_ctx is not None:
            self._lt_save_snapshot(s.lt_ctx, s.graph, "final")

        completed = sum(1 for n in s.graph.nodes.values() if n.status == NodeStatus.SUCCESS)
        failed = sum(1 for n in s.graph.nodes.values() if n.status == NodeStatus.FAILED)
        skipped = sum(1 for n in s.graph.nodes.values() if n.status == NodeStatus.SKIPPED)
        final_status = self.runtime._compute_graph_status(s.graph)

        if s.verification_passed and final_status == "failed" and completed > 0:
            logger.info(
                f"[GraphController] Recovery override: VerificationGate PASS with "
                f"{completed} succeeded / {failed} historically-failed node(s) "
                f"→ final_status overridden from 'failed' to 'success'"
            )
            final_status = "success"

        from app.avatar.runtime.graph.runtime.graph_runtime import ExecutionResult

        # Direct reply from Planner (no skill execution needed)
        if s.direct_reply:
            return ExecutionResult(
                success=True,
                final_status="success",
                completed_nodes=completed,
                failed_nodes=failed,
                skipped_nodes=skipped,
                graph=s.graph,
                summary=s.direct_reply,
            )

        _summary: Optional[str] = None
        try:
            from app.avatar.runtime.graph.controller.answer_synthesizer import AnswerSynthesizer
            _summary = AnswerSynthesizer.synthesize(s.graph, intent)
        except Exception as _synth_err:
            logger.debug(f"[GraphController] AnswerSynthesizer failed: {_synth_err}")

        result = ExecutionResult(
            success=final_status in ("success", "partial_success"),
            final_status=final_status,
            completed_nodes=completed,
            failed_nodes=failed,
            skipped_nodes=skipped,
            graph=s.graph,
            summary=_summary,
        )

        return result

    # ── DAG mode ────────────────────────────────────────────────────────

    async def _execute_dag_mode(
        self,
        intent: str,
        env_context: Dict[str, Any],
        config: Dict[str, Any],
    ) -> 'ExecutionResult':
        """Execute in DAG mode (one-shot planning with auto-repair)."""
        from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph

        max_planning_attempts = 3
        planning_attempt = 0

        _evo_trace_id: Optional[str] = None
        _session_id = env_context.get("session_id", "")
        if self._evolution_pipeline:
            try:
                _evo_trace = self._evolution_pipeline._trace_collector.create_trace(
                    task_id=env_context.get("task_id", "dag-unknown"),
                    session_id=_session_id,
                    goal=intent,
                    task_type=env_context.get("task_type", "dag"),
                )
                _evo_trace_id = _evo_trace.trace_id
            except Exception as _evo_err:
                logger.debug(f"[GraphController] DAG evolution trace creation failed: {_evo_err}")

        _final_result: Optional['ExecutionResult'] = None
        try:
            while planning_attempt < max_planning_attempts:
                planning_attempt += 1
                logger.info(f"Planning complete graph (DAG mode, attempt {planning_attempt}/{max_planning_attempts})")
                patch = await self.planner.plan_complete_graph(intent, env_context)

                repair_result = DagRepairHelper.auto_repair_dag(patch)
                if repair_result['repaired']:
                    logger.info(f"Auto-repaired DAG: {repair_result['repairs']}")
                    patch = repair_result['patch']

                if self.guard:
                    _empty_graph = ExecutionGraph(goal=intent, nodes={}, edges={})
                    validation = await self.guard.validate(patch, _empty_graph, context=env_context)
                    if not validation.approved:
                        logger.error(f"Patch validation failed: {validation.violations}")
                        if planning_attempt < max_planning_attempts:
                            logger.warning(f"Requesting new plan (attempt {planning_attempt + 1})")
                            continue
                        from app.avatar.runtime.graph.models.execution_graph import GraphStatus
                        graph = ExecutionGraph(goal=intent, nodes={}, edges={})
                        graph.status = GraphStatus.FAILED
                        _final_result = self._make_error_result(
                            graph,
                            error_message=f"Validation failed after {max_planning_attempts} attempts: {validation.violations}"
                        )
                        return _final_result

                graph = ExecutionGraph(goal=intent, nodes={}, edges={})
                self._apply_patch(patch, graph)
                _final_result = await self.runtime.execute_graph(graph)
                return _final_result

            logger.error(f"Failed to plan valid DAG after {max_planning_attempts} attempts")
            from app.avatar.runtime.graph.models.execution_graph import GraphStatus
            graph = ExecutionGraph(goal=intent, nodes={}, edges={})
            graph.status = GraphStatus.FAILED
            _final_result = self._make_error_result(
                graph, error_message=f"Failed to plan valid DAG after {max_planning_attempts} attempts"
            )
            return _final_result
        finally:
            # Emit task.completed via EventBus (unified event source)
            if _final_result and _final_result.graph and _final_result.graph.nodes:
                self._emit_task_completed(_final_result.graph, env_context)

            if self._evolution_pipeline and _evo_trace_id and _final_result:
                try:
                    from app.avatar.evolution.outcome_classifier import SubGoalResult
                    _evo_decision = f"dag_mode, final_status={_final_result.final_status}"
                    await self._evolution_pipeline.on_task_finished_v2(
                        task_id=env_context.get("task_id", "dag-unknown"),
                        session_id=_session_id,
                        goal=intent,
                        task_type=env_context.get("task_type", "dag"),
                        sub_goals=[SubGoalResult(name=intent, satisfied=_final_result.success)],
                        decision_basis=_evo_decision,
                    )
                except Exception as _evo_err:
                    logger.debug(f"[GraphController] DAG evolution pipeline failed (non-blocking): {_evo_err}")

    # ------------------------------------------------------------------
    # Multi-Agent mode (Requirements: 18.1, 18.2, 18.3, 18.4)
    # ------------------------------------------------------------------

    # Configurable dispatch table: node_type -> role_name
    _ROLE_DISPATCH_TABLE: Dict[str, str] = {
        "planner_node": "planner",
        "research_node": "researcher",
        "verification_node": "verifier",
        "recovery_node": "recovery",
        "synthesis_node": "supervisor",
        "standard": "executor",
    }

    @classmethod
    def register_role_dispatch(cls, node_type: str, role_name: str) -> None:
        """运行时注册新的节点类型到角色映射."""
        cls._ROLE_DISPATCH_TABLE[node_type] = role_name

    def _dispatch_to_role(self, node_type: str) -> str:
        """根据节点类型分派给对应角色. 使用可配置分派表."""
        return self._ROLE_DISPATCH_TABLE.get(node_type, "executor")

    async def _execute_multi_agent_mode(
        self,
        intent: str,
        env_context: Dict[str, Any],
        config: Dict[str, Any],
    ) -> 'ExecutionResult':
        """多 Agent 编排执行模式.

        完整流程:
        1. 组装 Supervisor 依赖
        2. 复杂度评估（低复杂度回退 react）
        3. LLM 分解意图 → SubtaskGraph
        4. GraphValidator 校验 DAG
        5. 按拓扑层级并行执行（每层内 asyncio.gather）
        6. 每个子任务委托 _execute_react_mode
        7. 上游结果注入下游上下文
        8. TerminationEvaluator 检查终止
        9. 合并结果
        """
        import asyncio
        import time as _time
        from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph, GraphStatus
        from app.avatar.runtime.graph.runtime.graph_runtime import ExecutionResult

        _start_mono = _time.monotonic()

        try:
            from app.avatar.runtime.multiagent.supervisor import (
                Supervisor, GraphValidator, TerminationEvaluator,
            )
            from app.avatar.runtime.multiagent.spawn_policy import SpawnPolicy
            from app.avatar.runtime.multiagent.role_spec import RoleSpecRegistry
            from app.avatar.runtime.multiagent.artifact import ArtifactStore
            from app.avatar.runtime.multiagent.trace_integration import TraceIntegration
            from app.avatar.runtime.multiagent.subtask_graph import (
                SubtaskGraph, SubtaskNode, SubtaskEdge,
            )

            # ── 1. 组装依赖（优先使用 Kernel 注册的实例，fallback 到新建） ──
            _kernel_registry = getattr(self, '_multi_agent_registry', None)
            _kernel_spawn_policy = getattr(self, '_multi_agent_spawn_policy', None)
            _kernel_artifact_store = getattr(self, '_multi_agent_artifact_store', None)

            role_registry = _kernel_registry if _kernel_registry is not None else RoleSpecRegistry()
            spawn_policy = _kernel_spawn_policy if _kernel_spawn_policy is not None else SpawnPolicy()
            artifact_store = _kernel_artifact_store if _kernel_artifact_store is not None else ArtifactStore()
            trace = TraceIntegration()

            supervisor = Supervisor(
                role_registry=role_registry,
                spawn_policy=spawn_policy,
                artifact_store=artifact_store,
                graph_controller=self,
                trace=trace,
                complexity_threshold=config.get("complexity_threshold", 3),
                max_rounds=config.get("max_rounds", 50),
                timeout_seconds=config.get("timeout_seconds", 3600.0),
            )

            graph_validator = GraphValidator(role_registry=role_registry)
            termination_eval = TerminationEvaluator(
                max_rounds=config.get("max_rounds", 50),
                timeout_seconds=config.get("timeout_seconds", 3600.0),
            )

            # ── 2. 复杂度评估 ──
            assessment = supervisor.evaluate_complexity(intent, env_context)
            trace.multi_agent_mode_decision(assessment.mode, assessment.reasoning)

            if assessment.mode == "single_agent":
                return await self._execute_react_mode(intent, env_context, config)

            trace.multi_agent_started(intent, "multi_agent")
            logger.info("[MultiAgent] 开始编排: %s", intent[:120])

            # ── 3. LLM 分解意图 → SubtaskGraph ──
            subtask_graph = await self._decompose_intent(intent, env_context)

            if not subtask_graph.nodes:
                logger.warning("[MultiAgent] 分解结果为空，回退 react")
                return await self._execute_react_mode(intent, env_context, config)

            # ── 4. DAG 校验 ──
            dag_ok, dag_errors = subtask_graph.validate_dag()
            if not dag_ok:
                logger.error("[MultiAgent] DAG 校验失败: %s，回退 react", dag_errors)
                return await self._execute_react_mode(intent, env_context, config)

            rules_ok, rules_errors = graph_validator.validate_rules(subtask_graph)
            if rules_ok:
                logger.info("[MultiAgent] 子任务图校验通过, %d 个节点", len(subtask_graph.nodes))
            else:
                logger.warning("[MultiAgent] 子任务图校验有问题: %s", rules_errors)

            # ── 5. 按拓扑层级并行执行 ──
            parallel_groups = subtask_graph.get_parallel_groups()
            subtask_results: Dict[str, Dict[str, Any]] = {}
            all_exec_results: list[ExecutionResult] = []
            _round = 0

            for layer_idx, layer_node_ids in enumerate(parallel_groups):
                # 终止检查
                _round += 1
                should_stop = termination_eval.check(_round, _start_mono, subtask_graph)
                if should_stop:
                    logger.info("[MultiAgent] TerminationEvaluator 触发终止, round=%d", _round)
                    break

                logger.info(
                    "[MultiAgent] 执行层 %d/%d, 节点: %s",
                    layer_idx + 1, len(parallel_groups), layer_node_ids,
                )

                # 为本层每个节点构建执行协程
                async def _run_subtask(node_id: str) -> tuple[str, ExecutionResult]:
                    node = subtask_graph.nodes[node_id]
                    node.status = "running"
                    trace.agent_task_assigned("supervisor", "supervisor", node_id)

                    # 收集上游结果注入上下文
                    upstream_ctx = self._collect_upstream_results(
                        node_id, subtask_graph, subtask_results,
                    )
                    # ── depth + budget propagation ──
                    _parent_depth = env_context.get("_execution_depth", 0)
                    _child_depth = _parent_depth + 1
                    # 父剩余预算 = 父 max_iterations - 已消耗（粗估为 0，因为子任务并行）
                    _parent_budget = env_context.get(
                        "_planner_budget",
                        self.max_planner_invocations_per_graph,
                    )
                    _n_siblings = max(len(layer_node_ids), 1)
                    _child_budget = max(
                        self.CHILD_BUDGET_MIN,
                        min(
                            self.CHILD_BUDGET_MAX,
                            int(_parent_budget * self.CHILD_BUDGET_RATIO / _n_siblings),
                        ),
                    )

                    sub_env = {**env_context, "upstream_results": upstream_ctx}
                    sub_env["subtask_description"] = node.description
                    sub_env["subtask_role"] = node.responsible_role
                    sub_env["_execution_depth"] = _child_depth
                    sub_env["_planner_budget"] = _child_budget

                    # 构建子任务 intent
                    sub_intent = self._build_subtask_intent(
                        node, intent, upstream_ctx,
                    )

                    try:
                        result = await self._execute_react_mode(
                            sub_intent, sub_env, config,
                        )
                        if result.success:
                            subtask_graph.mark_completed(node_id, {
                                "summary": result.summary or "",
                                "final_status": result.final_status,
                            })
                            trace.agent_task_completed("supervisor", "executor", node_id)
                        else:
                            subtask_graph.mark_failed(node_id)
                            logger.warning(
                                "[MultiAgent] 子任务 %s 失败: %s",
                                node_id, result.error_message,
                            )
                        return node_id, result
                    except Exception as sub_exc:
                        subtask_graph.mark_failed(node_id)
                        logger.error("[MultiAgent] 子任务 %s 异常: %s", node_id, sub_exc)
                        err_graph = ExecutionGraph(goal=sub_intent, nodes={}, edges={})
                        err_graph.status = GraphStatus.FAILED
                        return node_id, ExecutionResult(
                            graph=err_graph,
                            success=False,
                            final_status="failed",
                            error_message=str(sub_exc),
                        )

                # 并行执行本层所有子任务
                layer_tasks = [_run_subtask(nid) for nid in layer_node_ids]
                layer_results = await asyncio.gather(*layer_tasks, return_exceptions=True)

                for item in layer_results:
                    if isinstance(item, Exception):
                        logger.error("[MultiAgent] gather 异常: %s", item)
                        continue
                    nid, exec_result = item
                    subtask_results[nid] = {
                        "success": exec_result.success,
                        "summary": exec_result.summary or "",
                        "final_status": exec_result.final_status,
                    }
                    all_exec_results.append(exec_result)

            # ── 6. 合并结果 ──
            total_completed = sum(1 for r in all_exec_results if r.success)
            total_failed = sum(1 for r in all_exec_results if not r.success)
            all_success = subtask_graph.all_completed()
            elapsed = _time.monotonic() - _start_mono

            # 合成最终摘要
            result_data = supervisor.synthesize_results(subtask_graph)
            summaries = [
                f"[{nid}] {data.get('summary', '')}"
                for nid, data in subtask_results.items()
                if data.get("summary")
            ]
            final_summary = result_data.get("summary", "") or "\n".join(summaries)

            trace.multi_agent_completed(intent, "success" if all_success else "partial")

            logger.info(
                "[MultiAgent] 编排完成: %d/%d 成功, %.1fs",
                total_completed, len(subtask_graph.nodes), elapsed,
            )

            graph = ExecutionGraph(goal=intent, nodes={}, edges={})
            graph.status = GraphStatus.SUCCESS if all_success else GraphStatus.FAILED

            # Emit task.completed via EventBus (unified event source)
            # 传入子任务数量，避免空 graph 导致 step_count=0
            try:
                from app.avatar.runtime.events.types import Event, EventType
                if self.runtime.event_bus:
                    event = Event(
                        type=EventType.TASK_COMPLETED,
                        source="graph_controller",
                        payload={
                            "session_id": env_context.get("session_id", ""),
                            "task": {
                                "id": str(graph.id),
                                "status": "FAILED" if not all_success else "SUCCESS",
                            },
                            "step_count": len(subtask_graph.nodes),
                        },
                    )
                    self.runtime.event_bus.publish(event)
            except Exception as _evt_err:
                logger.debug("[EventEmitter] multi-agent task.completed failed: %s", _evt_err)

            return ExecutionResult(
                graph=graph,
                success=all_success,
                final_status="success" if all_success else "partial_success",
                completed_nodes=total_completed,
                failed_nodes=total_failed,
                execution_time=elapsed,
                summary=final_summary,
            )

        except Exception as exc:
            logger.error("[GraphController] multi_agent mode error: %s", exc, exc_info=True)
            # 异常回退到 react 模式
            logger.info("[MultiAgent] 异常回退 react 模式")
            try:
                return await self._execute_react_mode(intent, env_context, config)
            except Exception as fallback_exc:
                logger.error("[MultiAgent] react 回退也失败: %s", fallback_exc)
                graph = ExecutionGraph(goal=intent, nodes={}, edges={})
                graph.status = GraphStatus.FAILED
                return self._make_error_result(graph, error_message=str(exc))

    async def _decompose_intent(
        self,
        intent: str,
        env_context: Dict[str, Any],
    ) -> 'SubtaskGraph':
        """通过 Planner LLM 将意图分解为 SubtaskGraph.

        利用已有的 planner.plan_complete_graph 能力，将 DAG patch
        转换为 SubtaskGraph 结构。
        """
        from app.avatar.runtime.multiagent.subtask_graph import (
            SubtaskGraph, SubtaskNode, SubtaskEdge,
        )

        decompose_prompt = (
            f"将以下任务分解为可独立执行的子任务步骤。"
            f"每个子任务应该是一个完整的、可独立执行的工作单元。"
            f"最多分解为 8 个子任务，优先合并相关步骤。\n\n"
            f"任务: {intent}"
        )

        # 用 planner 做完整图规划
        try:
            patch = await self.planner.plan_complete_graph(decompose_prompt, env_context)
        except Exception as plan_err:
            logger.warning("[MultiAgent] planner 分解失败: %s, 构建单节点图", plan_err)
            # 分解失败 → 单节点图（整个任务作为一个子任务）
            graph = SubtaskGraph()
            node = SubtaskNode(
                node_id="task_0",
                description=intent,
                responsible_role="executor",
            )
            graph.nodes["task_0"] = node
            return graph

        # 将 patch actions 转换为 SubtaskGraph
        graph = SubtaskGraph()
        from app.avatar.runtime.graph.models.graph_patch import PatchOperation

        node_ids: list[str] = []
        for i, action in enumerate(patch.actions):
            if action.operation == PatchOperation.FINISH:
                continue
            node_id = f"task_{i}"
            desc = ""
            if hasattr(action, "node") and action.node:
                desc = getattr(action.node, "capability_name", "") or ""
                if hasattr(action.node, "params") and action.node.params:
                    params_str = str(action.node.params)
                    if len(params_str) < 500:
                        desc = f"{desc}: {params_str}" if desc else params_str
            if not desc:
                desc = f"Step {i + 1} of: {intent[:100]}"

            node = SubtaskNode(
                node_id=node_id,
                description=desc,
                responsible_role=self._dispatch_to_role(
                    getattr(action.node, "node_type", "standard") if hasattr(action, "node") and action.node else "standard"
                ),
            )
            graph.nodes[node_id] = node
            node_ids.append(node_id)

        # 顺序依赖：每个节点依赖前一个（planner 输出的是有序步骤）
        for j in range(1, len(node_ids)):
            graph.edges.append(SubtaskEdge(
                source_node_id=node_ids[j - 1],
                target_node_id=node_ids[j],
            ))

        # 安全上限：超过 12 个子任务时合并相邻节点（而非截断）
        MAX_SUBTASKS = 12
        if len(graph.nodes) > MAX_SUBTASKS:
            logger.info(
                "[MultiAgent] 子任务过多 (%d > %d), 合并相邻节点",
                len(graph.nodes), MAX_SUBTASKS,
            )
            graph = self._merge_subtask_graph(graph, MAX_SUBTASKS)

        logger.info("[MultiAgent] 分解完成: %d 个子任务", len(graph.nodes))
        return graph

    def _collect_upstream_results(
        self,
        node_id: str,
        subtask_graph: 'SubtaskGraph',
        subtask_results: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """收集指定节点的所有上游节点执行结果."""
        upstream: Dict[str, Any] = {}
        for edge in subtask_graph.edges:
            if edge.target_node_id == node_id:
                src = edge.source_node_id
                if src in subtask_results:
                    upstream[src] = subtask_results[src]
        return upstream

    @staticmethod
    def _merge_subtask_graph(
        graph: 'SubtaskGraph', target_count: int,
    ) -> 'SubtaskGraph':
        """将子任务图合并到 target_count 个节点，保留所有信息.

        策略：按拓扑顺序将相邻节点合并为一个组合节点，
        描述拼接（不丢失），角色取第一个节点的角色。
        """
        from app.avatar.runtime.multiagent.subtask_graph import (
            SubtaskGraph, SubtaskNode, SubtaskEdge,
        )

        ordered_ids = list(graph.nodes.keys())
        n = len(ordered_ids)
        if n <= target_count:
            return graph

        # 均匀分组
        group_size = n / target_count
        groups: list[list[str]] = []
        current_group: list[str] = []
        for i, nid in enumerate(ordered_ids):
            current_group.append(nid)
            if len(current_group) >= group_size and len(groups) < target_count - 1:
                groups.append(current_group)
                current_group = []
        if current_group:
            groups.append(current_group)

        # 构建合并后的图
        merged = SubtaskGraph()
        merged_ids: list[str] = []
        for gi, group in enumerate(groups):
            merged_id = f"merged_{gi}"
            descriptions = []
            role = graph.nodes[group[0]].responsible_role
            for nid in group:
                descriptions.append(graph.nodes[nid].description)
            merged_desc = " → ".join(descriptions)
            merged.nodes[merged_id] = SubtaskNode(
                node_id=merged_id,
                description=merged_desc,
                responsible_role=role,
            )
            merged_ids.append(merged_id)

        for j in range(1, len(merged_ids)):
            merged.edges.append(SubtaskEdge(
                source_node_id=merged_ids[j - 1],
                target_node_id=merged_ids[j],
            ))

        logger.info(
            "[MultiAgent] 合并完成: %d → %d 个节点", n, len(merged.nodes),
        )
        return merged

    def _build_subtask_intent(
        self,
        node: 'SubtaskNode',
        original_intent: str,
        upstream_results: Dict[str, Any],
    ) -> str:
        """构建子任务的 intent 字符串，注入上游上下文."""
        parts = [node.description]

        if upstream_results:
            ctx_lines = []
            for src_id, data in upstream_results.items():
                summary = data.get("summary", "")
                if summary:
                    ctx_lines.append(f"- {src_id}: {summary[:300]}")
            if ctx_lines:
                parts.append(f"\n\n前置步骤结果:\n" + "\n".join(ctx_lines))

        parts.append(f"\n\n（原始任务: {original_intent[:200]}）")
        return "".join(parts)
