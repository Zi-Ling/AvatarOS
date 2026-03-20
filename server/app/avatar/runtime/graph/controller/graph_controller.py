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

        # ── Task understanding layer ────────────────────────────────────
        s.task_def, s.readiness, s.complexity, s.task_runtime_state = (
            await self._setup_task_understanding(intent, s.env_context, s.graph)
        )

        # ── Complexity-based routing ────────────────────────────────────
        _routed = await self._try_complexity_routing(s)
        if _routed is not None:
            return _routed

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
                    await s.lifecycle.on_plan_generated(
                        planner_input={"goal": intent, "graph_nodes": len(s.graph.nodes)},
                        planner_output={"actions": len(patch.actions)},
                        tokens_used=_patch_meta.get("tokens_used", 0),
                        cost_usd=_patch_meta.get("cost", 0.0),
                        latency_ms=_plan_latency_ms,
                    )

                # ── FINISH handling ─────────────────────────────────────
                if is_finish:
                    _finish_action = await self._handle_finish_decision(s)
                    if _finish_action == "continue":
                        continue
                    elif _finish_action in ("break_partial", "break_failed", "break_uncertain"):
                        return s.final_result
                    # "break" or "break_pass" → fall through to break
                    break

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

                # ── Narrative: step.start for pending nodes ─────────────
                s.pending_node_ids = set()
                from app.avatar.runtime.narrative.models import TranslationContext as _TC
                for _n in s.graph.nodes.values():
                    if _n.status == NodeStatus.PENDING:
                        s.pending_node_ids.add(_n.id)
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

                # ── Post-execution processing ───────────────────────────
                await self._record_evolution_steps(s)

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

                # Uncovered sub-goals after success
                _uncov_action = self._check_uncovered_after_success(s, result)
                if _uncov_action == "continue":
                    continue

            # ── FINISH: compute final result ────────────────────────────
            s.final_result = self._compute_final_result(s, intent)
            return s.final_result

        finally:
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

    async def _try_complexity_routing(self, s: ReactLoopState) -> Optional['ExecutionResult']:
        """Attempt complexity-based routing (batch/phased). Returns result if routed."""
        if s.complexity is None:
            return None

        if s.complexity.task_type == "template_batch" and self._batch_plan_builder is not None:
            try:
                self._batch_plan_builder.build(s.complexity.batch_params, s.task_def)
                return await self._execute_dag_mode(s.intent, s.env_context, s.config)
            except Exception as _bpb_err:
                logger.warning(f"[GraphController] BatchPlanBuilder failed, falling back to ReAct: {_bpb_err}")

        if s.complexity.task_type == "complex" and self._phased_planner is not None:
            try:
                if self._phased_planner.should_activate(s.complexity, s.task_def, s.readiness, s.env_context):
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

        return None

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

        _summary: Optional[str] = None
        try:
            from app.avatar.runtime.graph.controller.answer_synthesizer import AnswerSynthesizer
            _summary = AnswerSynthesizer.synthesize(s.graph, intent)
        except Exception as _synth_err:
            logger.debug(f"[GraphController] AnswerSynthesizer failed: {_synth_err}")

        return ExecutionResult(
            success=final_status in ("success", "partial_success"),
            final_status=final_status,
            completed_nodes=completed,
            failed_nodes=failed,
            skipped_nodes=skipped,
            graph=s.graph,
            summary=_summary,
        )

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
