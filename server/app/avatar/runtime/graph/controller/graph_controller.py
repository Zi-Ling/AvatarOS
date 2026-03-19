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

        max_react_iterations = config.get('max_react_iterations', 200)
        max_graph_nodes = config.get('max_graph_nodes', 200)

        # ── Setup: session, graph, workspace, goals, deliverables ───────
        _setup = await self._setup_react_session(intent, env_context, config)
        _exec_session_id = _setup.exec_session_id
        _lifecycle = _setup.lifecycle
        graph = _setup.graph
        _shared_context = _setup.shared_context
        _workspace = _setup.workspace
        _session_id = _setup.session_id
        sub_goals = _setup.sub_goals
        _deliverables = _setup.deliverables
        env_context = _setup.env_context

        # ── Task understanding layer ────────────────────────────────────
        _task_def, _readiness, _complexity, _task_runtime_state = (
            await self._setup_task_understanding(intent, env_context, graph)
        )

        # ── Complexity-based routing ────────────────────────────────────
        if _complexity is not None:
            if _complexity.task_type == "template_batch" and self._batch_plan_builder is not None:
                try:
                    self._batch_plan_builder.build(_complexity.batch_params, _task_def)
                    return await self._execute_dag_mode(intent, env_context, config)
                except Exception as _bpb_err:
                    logger.warning(f"[GraphController] BatchPlanBuilder failed, falling back to ReAct: {_bpb_err}")

            if _complexity.task_type == "complex" and self._phased_planner is not None and _task_def is not None:
                try:
                    if self._phased_planner.should_activate(_task_def, _complexity, _readiness):
                        _goal_plan = await self._phased_planner.plan(_task_def)
                        return await self._phased_planner.execute(_goal_plan, self)
                except Exception as _pp_err:
                    logger.warning(f"[GraphController] PhasedPlanner failed, falling back to ReAct: {_pp_err}")

        # ── Long-task runtime context ───────────────────────────────────
        _lt_ctx = LongTaskContext.from_env(env_context)

        # ── NarrativeManager ────────────────────────────────────────────
        _narrative_manager = self._setup_narrative_manager(
            _session_id, _exec_session_id, str(graph.id), intent, sub_goals
        )

        # ── Per-task state reset ────────────────────────────────────────
        planner_invocations = 0
        _handle = control_handle
        _consecutive_failures = 0
        _MAX_CONSECUTIVE_FAILURES = 3

        _is_simple = env_context.get("simple_task_mode", False)
        self._budget.reset()
        self._planner_usage = self._budget._usage
        self._goal_tracker.reset()

        _lifecycle_status = "failed"
        _result_status = "unknown"
        _error_message: Optional[str] = None
        _final_result: Optional['ExecutionResult'] = None
        _verification_passed = False

        # ── Evolution trace ─────────────────────────────────────────────
        _evo_trace_id: Optional[str] = None
        if self._evolution_pipeline:
            try:
                _evo_trace = self._evolution_pipeline._trace_collector.create_trace(
                    task_id=str(graph.id),
                    session_id=_session_id or _exec_session_id,
                    goal=intent,
                    task_type=env_context.get("task_type", "unknown"),
                )
                _evo_trace_id = _evo_trace.trace_id
            except Exception as _evo_err:
                logger.debug(f"[GraphController] Evolution trace creation failed: {_evo_err}")

        try:
            while True:
                # ── Cancel / Pause check ────────────────────────────────
                if _handle is not None and _handle.is_cancelled():
                    logger.info("[GraphController] Cancellation signal received")
                    from app.avatar.runtime.graph.models.execution_graph import GraphStatus
                    graph.status = GraphStatus.FAILED
                    _lifecycle_status = "cancelled"
                    _result_status = "cancelled"
                    _error_message = "Task cancelled by user"
                    if _lt_ctx is not None:
                        self._lt_save_snapshot(_lt_ctx, graph, "pre_cancel")
                    _final_result = self._make_error_result(graph, error_message=_error_message)
                    return _final_result

                if _handle is not None:
                    await _handle.wait_if_paused()
                    if _handle.is_cancelled():
                        logger.info("[GraphController] Cancelled after resume")
                        from app.avatar.runtime.graph.models.execution_graph import GraphStatus
                        graph.status = GraphStatus.FAILED
                        _lifecycle_status = "cancelled"
                        _result_status = "cancelled"
                        _error_message = "Task cancelled by user"
                        _final_result = self._make_error_result(graph, error_message=_error_message)
                        return _final_result

                # ── Hard iteration limits ───────────────────────────────
                if planner_invocations >= self.max_planner_invocations_per_graph:
                    _error_message = f"Exceeded max planner invocations: {planner_invocations}"
                    logger.error(_error_message)
                    from app.avatar.runtime.graph.models.execution_graph import GraphStatus
                    graph.status = GraphStatus.FAILED
                    _final_result = self._make_error_result(graph, error_message=_error_message)
                    return _final_result

                if planner_invocations >= max_react_iterations:
                    _error_message = f"Exceeded max ReAct iterations: {planner_invocations}"
                    logger.error(_error_message)
                    from app.avatar.runtime.graph.models.execution_graph import GraphStatus
                    graph.status = GraphStatus.FAILED
                    _final_result = self._make_error_result(graph, error_message=_error_message)
                    return _final_result

                if len(graph.nodes) >= max_graph_nodes:
                    _error_message = f"Exceeded max graph nodes: {len(graph.nodes)}"
                    logger.error(_error_message)
                    from app.avatar.runtime.graph.models.execution_graph import GraphStatus
                    graph.status = GraphStatus.FAILED
                    _final_result = self._make_error_result(graph, error_message=_error_message)
                    return _final_result

                # ── Budget check ────────────────────────────────────────
                budget_error = self._budget.check()
                if budget_error:
                    _error_message = f"Planner budget exceeded: {budget_error}"
                    logger.error(f"[BudgetGuard] {_error_message}")
                    from app.avatar.runtime.graph.models.execution_graph import GraphStatus
                    graph.status = GraphStatus.FAILED
                    _final_result = self._make_error_result(graph, error_message=_error_message)
                    return _final_result

                # ── Coverage hint injection ─────────────────────────────
                _coverage_summary = env_context.get("goal_coverage_summary")
                if _coverage_summary is not None:
                    try:
                        from app.avatar.runtime.verification.finish_bias_check import FinishBiasCheck
                        env_context = FinishBiasCheck().inject(env_context, _coverage_summary)
                    except Exception:
                        pass

                # ── Terminal evidence short-circuit ─────────────────────
                if planner_invocations > 0 and len(graph.nodes) > 0:
                    _te_reason = self._goal_tracker.check_terminal_evidence(graph, sub_goals, env_context)
                    if _te_reason:
                        logger.info(f"[TerminalEvidence] Short-circuit: {_te_reason}")
                        break

                # ── Plan ────────────────────────────────────────────────
                planner_invocations += 1
                logger.info(
                    f"Planner invocation {planner_invocations}/{self._budget.effective_max_calls}"
                )
                _plan_start = time.monotonic()
                try:
                    patch = await self.planner.plan_next_step(graph, env_context)
                except Exception as _plan_err:
                    _plan_latency_ms = int((time.monotonic() - _plan_start) * 1000)
                    # ── Truncation recovery: inject hint and retry ──────
                    from app.avatar.planner.planners.interactive import PlannerTruncationError
                    if isinstance(_plan_err, PlannerTruncationError):
                        _truncation_retries = env_context.get("_truncation_retries", 0)
                        _MAX_TRUNCATION_RETRIES = 2
                        if _truncation_retries >= _MAX_TRUNCATION_RETRIES:
                            logger.error(
                                f"[GraphController] Truncation retry exhausted "
                                f"({_truncation_retries}/{_MAX_TRUNCATION_RETRIES})"
                            )
                            _error_message = f"Planner output truncated {_truncation_retries + 1} times: {_plan_err}"
                            from app.avatar.runtime.graph.models.execution_graph import GraphStatus
                            graph.status = GraphStatus.FAILED
                            _final_result = self._make_error_result(graph, error_message=_error_message)
                            return _final_result
                        logger.warning(
                            f"[GraphController] Planner output truncated "
                            f"(skill={_plan_err.skill_name}), injecting hint "
                            f"and retrying ({_truncation_retries + 1}/{_MAX_TRUNCATION_RETRIES})"
                        )
                        env_context = dict(env_context)
                        env_context["_truncation_retries"] = _truncation_retries + 1
                        env_context["truncation_hint"] = (
                            "Your previous output was TRUNCATED by the token limit. "
                            "The framework could not parse your response. To avoid this:\n"
                            "1. Keep your `thought` field SHORT (1-2 sentences max).\n"
                            "2. Simplify your action — do ONE thing at a time.\n"
                            "3. If using python.run, write SHORTER code. Split complex "
                            "operations into multiple steps.\n"
                            "4. Do NOT embed large data literals in params."
                        )
                        # Directed recovery: escalating constraints
                        env_context["recovery_constraints"] = {
                            "force_single_action": True,
                            "max_thought_words": 30,
                            "max_code_lines": 20 if _truncation_retries == 0 else 10,
                            "reason": "truncation",
                        }
                        continue
                    # Non-truncation errors: propagate as before
                    raise
                _plan_latency_ms = int((time.monotonic() - _plan_start) * 1000)

                # Clear truncation hint on successful plan (avoid stale hint)
                if "truncation_hint" in env_context:
                    env_context = dict(env_context)
                    env_context.pop("truncation_hint", None)

                # Clear schema violation hint on successful plan
                if "schema_violation_hint" in env_context:
                    env_context = dict(env_context)
                    env_context.pop("schema_violation_hint", None)

                # Clear recovery constraints on successful plan
                if "recovery_constraints" in env_context:
                    env_context = dict(env_context)
                    env_context.pop("recovery_constraints", None)

                self._budget.track(patch)
                _patch_meta = (patch.metadata or {}) if patch else {}

                is_finish = patch is None or (
                    len(patch.actions) == 1 and
                    patch.actions[0].operation == PatchOperation.FINISH
                )

                if not is_finish:
                    await _lifecycle.on_plan_generated(
                        planner_input={"goal": intent, "graph_nodes": len(graph.nodes)},
                        planner_output={"actions": len(patch.actions)},
                        tokens_used=_patch_meta.get("tokens_used", 0),
                        cost_usd=_patch_meta.get("cost", 0.0),
                        latency_ms=_plan_latency_ms,
                    )

                if is_finish:
                    logger.info("Planner returned FINISH")
                    uncovered = self._goal_tracker.get_uncovered_sub_goals(sub_goals, graph)
                    if uncovered:
                        logger.warning(
                            f"[GoalTracker] FINISH rejected: {len(uncovered)} uncovered: {uncovered}"
                        )
                        env_context = dict(env_context)
                        env_context["uncovered_sub_goals"] = uncovered
                        env_context["goal_tracker_hint"] = (
                            f"The following sub-goals are NOT yet completed: {uncovered}. "
                            f"You MUST complete them before finishing."
                        )
                        continue

                    # ── Deliverable coverage check ──────────────────────
                    if _deliverables:
                        _unsatisfied = self._goal_tracker.get_unsatisfied_deliverables(
                            _deliverables, graph
                        )
                        if _unsatisfied:
                            _missing_fmts = [f"{d.id}:{d.format}" for d in _unsatisfied]
                            logger.warning(
                                f"[GoalTracker] FINISH rejected: {len(_unsatisfied)} "
                                f"unsatisfied deliverables: {_missing_fmts}"
                            )
                            env_context = dict(env_context)
                            env_context["unsatisfied_deliverables"] = _missing_fmts
                            env_context["goal_tracker_hint"] = (
                                f"The following deliverables have NOT been produced yet: "
                                f"{_missing_fmts}. You MUST produce ALL requested file "
                                f"formats before finishing."
                            )
                            continue

                    # ── Long-task: DeliveryGate ─────────────────────────
                    if _lt_ctx is not None:
                        _dg_result = await self._lt_run_delivery_gate(_lt_ctx)
                        if _dg_result and not _dg_result.get("passed", True):
                            logger.warning(
                                f"[DeliveryGate] Not passed: {_dg_result.get('reasons')}"
                            )
                            env_context = dict(env_context)
                            env_context["delivery_gate_reasons"] = _dg_result.get("reasons", [])
                            env_context["goal_tracker_hint"] = (
                                f"Delivery gate check failed: {_dg_result.get('reasons')}. "
                                f"Please address these issues before finishing."
                            )
                            continue

                    # ── Narrative: verification events ───────────────────
                    from app.avatar.runtime.narrative.models import TranslationContext as _TC
                    try:
                        await _narrative_manager.on_event(
                            "verification.start",
                            step_id="__run__",
                            context=_TC(),
                        )
                    except Exception as _ne:
                        logger.debug(f"[GraphController] Narrative verification.start failed: {_ne}")

                    _gate_result = await self._run_verification_gate(
                        intent=intent, graph=graph, workspace=_workspace,
                        env_context=env_context,
                        session_id=_session_id or _exec_session_id,
                        task_context=None,
                    )

                    try:
                        if _gate_result == "break_pass":
                            await _narrative_manager.on_event(
                                "verification.pass",
                                step_id="__run__",
                                context=_TC(),
                            )
                        elif _gate_result == "break_partial":
                            await _narrative_manager.on_event(
                                "verification.fail",
                                step_id="__run__",
                                context=_TC(reason="部分完成"),
                            )
                        elif _gate_result in ("break_failed", "break_uncertain"):
                            await _narrative_manager.on_event(
                                "verification.fail",
                                step_id="__run__",
                                context=_TC(reason="验证失败"),
                            )
                        elif _gate_result == "continue":
                            await _narrative_manager.on_event(
                                "verification.fail",
                                step_id="__run__",
                                context=_TC(reason="验证未通过，准备重试"),
                            )
                            _hint = (env_context.get("verification_failed_hints") or ["正在重新分析失败原因"])[0]
                            await _narrative_manager.on_event(
                                "retry.triggered",
                                step_id="__run__",
                                context=_TC(
                                    reason=_hint,
                                    retry_count=1,
                                ),
                            )
                    except Exception as _ne:
                        logger.debug(f"[GraphController] Narrative verification event failed: {_ne}")

                    if _gate_result == "continue":
                        env_context = dict(env_context)
                        continue
                    elif _gate_result == "break_partial":
                        _lifecycle_status = "completed"
                        _result_status = "partial_success"
                        from app.avatar.runtime.graph.runtime.graph_runtime import ExecutionResult
                        _final_result = ExecutionResult(
                            success=False, final_status="partial_success",
                            completed_nodes=sum(1 for n in graph.nodes.values() if n.status == NodeStatus.SUCCESS),
                            failed_nodes=sum(1 for n in graph.nodes.values() if n.status == NodeStatus.FAILED),
                            skipped_nodes=sum(1 for n in graph.nodes.values() if n.status == NodeStatus.SKIPPED),
                            graph=graph,
                        )
                        return _final_result
                    elif _gate_result == "break_failed":
                        _lifecycle_status = "failed"
                        _result_status = "failed"
                        _final_result = self._make_error_result(graph, "Verification failed: repair exhausted")
                        return _final_result
                    elif _gate_result == "break_uncertain":
                        _lifecycle_status = "failed"
                        _result_status = "uncertain_terminal"
                        _final_result = self._make_error_result(graph, "Verification uncertain: high-risk task requires human review")
                        return _final_result

                    if _gate_result == "break_pass":
                        _verification_passed = True

                    logger.info("Planner returned FINISH -- all sub-goals covered")
                    break

                # ── Guard validate ──────────────────────────────────────
                if self.guard:
                    validation = await self.guard.validate(patch, graph, context=env_context)
                    await _lifecycle.on_policy_evaluated(
                        approved=validation.approved,
                        violations=validation.violations,
                        warnings=validation.warnings,
                        requires_approval=validation.requires_approval,
                    )
                    if not validation.approved:
                        _error_message = f"Patch validation failed: {validation.violations}"
                        logger.error(_error_message)
                        from app.avatar.runtime.graph.models.execution_graph import GraphStatus
                        graph.status = GraphStatus.FAILED
                        _final_result = self._make_error_result(graph, error_message=_error_message)
                        return _final_result

                # ── ActionSchemaValidator: required params gate ──────────
                try:
                    from app.avatar.runtime.graph.guard.action_schema_validator import validate_patch_schemas
                    _schema_violations = validate_patch_schemas(patch)
                    if _schema_violations:
                        _schema_replan_key = "_schema_replan_count"
                        _schema_replans = env_context.get(_schema_replan_key, 0)
                        _MAX_SCHEMA_REPLANS = 2
                        if _schema_replans >= _MAX_SCHEMA_REPLANS:
                            _error_message = (
                                f"Schema validation failed {_schema_replans + 1} times: "
                                + "; ".join(v.to_hint() for v in _schema_violations)
                            )
                            logger.error(f"[ActionSchemaValidator] {_error_message}")
                            from app.avatar.runtime.graph.models.execution_graph import GraphStatus
                            graph.status = GraphStatus.FAILED
                            _final_result = self._make_error_result(graph, error_message=_error_message)
                            return _final_result
                        _hint_lines = [v.to_hint() for v in _schema_violations]
                        logger.warning(
                            f"[ActionSchemaValidator] Replan ({_schema_replans + 1}/{_MAX_SCHEMA_REPLANS}): "
                            + "; ".join(_hint_lines)
                        )
                        env_context = dict(env_context)
                        env_context[_schema_replan_key] = _schema_replans + 1
                        env_context["schema_violation_hint"] = (
                            "Your proposed action has MISSING REQUIRED PARAMETERS and was rejected.\n"
                            + "\n".join(f"- {h}" for h in _hint_lines)
                            + "\nPlease re-submit with ALL required parameters filled in."
                        )
                        # Directed recovery: force planner to focus on correct params
                        env_context["recovery_constraints"] = {
                            "force_single_action": True,
                            "max_thought_words": 30,
                            "reason": "schema_violation",
                        }
                        continue
                except Exception as _sv_err:
                    logger.debug(f"[ActionSchemaValidator] Check skipped: {_sv_err}")

                # ── ClarificationGate ───────────────────────────────────
                if self._collaboration_gate is not None and _task_def is not None:
                    try:
                        _clar_req = self._collaboration_gate.check_clarification_needed(patch, _task_def)
                        if _clar_req is not None:
                            await self._collaboration_gate.suspend(_clar_req, env_context)
                    except Exception as _cg_err:
                        logger.debug(f"[ClarificationGate] Check skipped: {_cg_err}")

                # ── Dedup + Apply patch ─────────────────────────────────
                patch = self._dedup.deduplicate_patch(patch, graph)
                if patch is None:
                    _dedup_replan_key = "_dedup_replan_used"
                    if env_context.get(_dedup_replan_key):
                        logger.info(
                            "[DedupGuard] Replan already used — all nodes "
                            "still duplicates → FINISH"
                        )
                        break
                    logger.info(
                        "[DedupGuard] All nodes duplicates — injecting "
                        "hint and giving Planner one replan chance"
                    )
                    env_context = dict(env_context)
                    env_context[_dedup_replan_key] = True
                    env_context["dedup_hint"] = (
                        "Your last proposed step(s) are intent-equivalent to "
                        "already-succeeded nodes and were filtered. "
                        "If the task goal is already answered, output FINISH. "
                        "Otherwise, propose a DIFFERENT step (e.g. llm.fallback "
                        "to synthesize a final answer from existing results)."
                    )
                    continue

                self._apply_patch(patch, graph, lt_ctx=_lt_ctx, env_context=env_context)
                self._emit_plan_generated(graph, env_context)

                # ── ParamBinder ─────────────────────────────────────────
                resolved_inputs = env_context.get("resolved_inputs")
                if resolved_inputs:
                    from app.avatar.runtime.context.param_binder import bind_params
                    for node in graph.nodes.values():
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

                await _lifecycle.on_execution_started()

                # ── Narrative: step.start for pending nodes ─────────────
                from app.avatar.runtime.narrative.models import TranslationContext as _TC
                _pending_node_ids: set = set()
                for _n in graph.nodes.values():
                    if _n.status == NodeStatus.PENDING:
                        _pending_node_ids.add(_n.id)
                        try:
                            await _narrative_manager.on_event(
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
                if self._collaboration_gate is not None and _task_def is not None:
                    try:
                        from app.avatar.runtime.graph.models.step_node import NodeStatus as _NS
                        for _pn in graph.nodes.values():
                            if _pn.status == _NS.PENDING:
                                _approval_req = self._collaboration_gate.check_approval_needed(_pn, _task_def)
                                if _approval_req is not None:
                                    await self._collaboration_gate.suspend(_approval_req, env_context)
                    except Exception as _ag_err:
                        logger.debug(f"[ApprovalGate] Check skipped: {_ag_err}")

                # ── Execute ready nodes ─────────────────────────────────
                _has_fan_nodes = False
                try:
                    from app.avatar.runtime.graph.models.step_node import NodeType as _NT
                    for _fn in list(graph.nodes.values()):
                        _node_type = getattr(_fn, "node_type", None)
                        if _node_type == _NT.FAN_OUT and _fn.status == NodeStatus.PENDING:
                            _has_fan_nodes = True
                            await self._execute_fan_out_node(_fn, graph, _shared_context)
                        elif _node_type == _NT.FAN_IN and _fn.status == NodeStatus.PENDING:
                            _upstream_done = all(
                                graph.nodes.get(e.source_node) is not None and
                                graph.nodes[e.source_node].status in (NodeStatus.SUCCESS, NodeStatus.FAILED, NodeStatus.SKIPPED)
                                for e in graph.edges.values()
                                if e.target_node == _fn.id
                            )
                            if _upstream_done:
                                _has_fan_nodes = True
                                self._execute_fan_in_node(_fn, graph)
                except Exception as _fan_err:
                    logger.debug(f"[FanOut/FanIn] Check skipped: {_fan_err}")

                result = await self.runtime.execute_ready_nodes(graph, context=_shared_context)

                # ── Evolution: record completed/failed nodes ────────────
                if self._evolution_pipeline and _evo_trace_id:
                    try:
                        for _n in graph.nodes.values():
                            if _n.status in (NodeStatus.SUCCESS, NodeStatus.FAILED):
                                _node_meta = _n.metadata or {}
                                if _node_meta.get("_evo_recorded"):
                                    continue
                                _step_status = "success" if _n.status == NodeStatus.SUCCESS else "failed"
                                _step_output = _n.outputs if _n.status == NodeStatus.SUCCESS else None
                                _step_error = _n.error_message if _n.status == NodeStatus.FAILED else None
                                _step_duration = int(_node_meta.get("duration_ms", 0))
                                self._evolution_pipeline._trace_collector.record_step(
                                    trace_id=_evo_trace_id,
                                    step_id=_n.id,
                                    skill_name=_n.capability_name,
                                    input_params=_n.params,
                                    output=_step_output,
                                    status=_step_status,
                                    duration_ms=_step_duration,
                                    error=_step_error,
                                )
                                _n.metadata = _node_meta
                                _n.metadata["_evo_recorded"] = True
                    except Exception as _evo_step_err:
                        logger.debug(f"[GraphController] Evolution step recording failed: {_evo_step_err}")

                # ── Long-task: persist step states + artifacts ──────────
                if _lt_ctx is not None:
                    await self._lt_persist_step_results(graph, _lt_ctx)

                # ── Narrative: step.end / step.failed / artifact.created ───
                try:
                    for _n in graph.nodes.values():
                        if _n.id not in _pending_node_ids:
                            continue
                        if _n.status == NodeStatus.SUCCESS:
                            await _narrative_manager.on_event(
                                "step.end",
                                step_id=str(_n.id),
                                context=_TC(
                                    skill_name=_n.capability_name,
                                    output_summary=self._summarize_output(_n),
                                    semantic_label=self._get_semantic_label(_n),
                                ),
                            )
                            _oc = _n.metadata.get("output_contract") if _n.metadata else None
                            if _oc is not None:
                                _artifacts = _oc if isinstance(_oc, list) else [_oc]
                                for _art in _artifacts:
                                    _art_dict = _art if isinstance(_art, dict) else (
                                        getattr(_art, "__dict__", {}) if hasattr(_art, "__dict__") else {}
                                    )
                                    _art_path = _art_dict.get("path")
                                    if _art_path:
                                        _art_kind = _art_dict.get("kind", "file")
                                        _art_label = _art_dict.get("semantic_label") or _art_path.rsplit("/", 1)[-1]
                                        await _narrative_manager.on_event(
                                            "artifact.created",
                                            step_id=str(_n.id),
                                            context=_TC(
                                                artifact_type=_art_kind,
                                                artifact_label=_art_label,
                                            ),
                                        )
                        elif _n.status == NodeStatus.FAILED:
                            await _narrative_manager.on_event(
                                "step.failed",
                                step_id=str(_n.id),
                                context=_TC(
                                    skill_name=_n.capability_name,
                                    error_message=_n.error_message or "未知错误",
                                    semantic_label=self._get_semantic_label(_n),
                                ),
                            )
                            if _n.can_retry():
                                await _narrative_manager.on_event(
                                    "retry.triggered",
                                    step_id=str(_n.id),
                                    context=_TC(
                                        skill_name=_n.capability_name,
                                        retry_count=_n.retry_count,
                                        reason=_n.error_message or "执行失败",
                                    ),
                                )
                except Exception as _ne:
                    logger.debug(f"[GraphController] Narrative step events failed: {_ne}")

                # ── Long-task: routine checkpoint ───────────────────────
                if _lt_ctx is not None:
                    _lt_ctx.step_count_since_checkpoint += 1
                    if _lt_ctx.step_count_since_checkpoint >= _lt_ctx.checkpoint_interval:
                        await self._lt_create_routine_checkpoint(_lt_ctx)
                        _lt_ctx.step_count_since_checkpoint = 0

                # ── Execution cost budget ───────────────────────────────
                if self.max_execution_cost:
                    from app.avatar.runtime.graph.context.execution_context import ExecutionContext
                    if not hasattr(graph, '_context'):
                        graph._context = ExecutionContext(graph_id=graph.id)
                    current_cost = self.runtime.get_execution_cost(graph, graph._context)
                    if current_cost >= self.max_execution_cost:
                        _error_message = (
                            f"Execution cost exceeded: ${current_cost:.4f} >= "
                            f"${self.max_execution_cost:.4f}"
                        )
                        logger.error(f"[GraphController] {_error_message}")
                        from app.avatar.runtime.graph.models.execution_graph import GraphStatus
                        graph.status = GraphStatus.FAILED
                        _final_result = self._make_error_result(graph, error_message=_error_message)
                        return _final_result

                # ── Circuit breaker ─────────────────────────────────────
                # Check if THIS round's newly executed nodes all failed.
                # We must not count historical failures from previous rounds
                # (e.g. step_2 failed in round 2, but step_4 succeeded in
                # round 4 — that's not a consecutive failure).
                _this_round_has_new_success = any(
                    nid in _pending_node_ids and n.status == NodeStatus.SUCCESS
                    for nid, n in graph.nodes.items()
                )
                if result.final_status in ("failed", "partial_success") and not _this_round_has_new_success:
                    _consecutive_failures += 1
                    logger.info(
                        f"[ReAct] Node(s) failed — "
                        f"consecutive_failures={_consecutive_failures}/{_MAX_CONSECUTIVE_FAILURES}"
                    )
                    if _consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                        logger.warning(
                            f"[CircuitBreaker] {_consecutive_failures} consecutive failures — "
                            f"force-terminating"
                        )
                        _error_message = (
                            f"Circuit breaker: {_consecutive_failures} consecutive failures"
                        )
                        _final_result = self._make_error_result(graph, error_message=_error_message)
                        return _final_result
                elif _this_round_has_new_success:
                    _consecutive_failures = 0

                # ── TaskRuntimeState update ─────────────────────────────
                if _task_runtime_state is not None:
                    try:
                        from app.avatar.runtime.task.runtime_state import UpdateSource
                        for _rn in graph.nodes.values():
                            if _rn.status == NodeStatus.SUCCESS:
                                _task_runtime_state.add_completed_item(
                                    item_id=_rn.id,
                                    description=f"{_rn.capability_name}: {(_rn.metadata or {}).get('description', 'completed')}",
                                    update_source=UpdateSource.NODE_STATUS_AGGREGATION,
                                )
                    except Exception as _trs_upd_err:
                        logger.debug(f"[TaskRuntimeState] Update failed: {_trs_upd_err}")

                # ── DeliverableState tracking ───────────────────────────
                if _deliverables:
                    try:
                        from app.avatar.runtime.verification.models import DeliverableState
                        _del_states: Dict[str, 'DeliverableState'] = env_context.get(
                            "deliverable_states", {}
                        )
                        if not _del_states:
                            for _d in _deliverables:
                                _del_states[_d.id] = DeliverableState(deliverable_id=_d.id)
                            env_context["deliverable_states"] = _del_states

                        for _rn in graph.nodes.values():
                            if _rn.status != NodeStatus.SUCCESS:
                                continue
                            _node_outputs = _rn.outputs or {}
                            _node_paths: List[str] = []
                            for _ov in _node_outputs.values():
                                if isinstance(_ov, str) and "." in _ov:
                                    _node_paths.append(_ov)
                                elif isinstance(_ov, dict):
                                    _p = _ov.get("path") or _ov.get("file_path") or ""
                                    if _p:
                                        _node_paths.append(_p)
                                elif isinstance(_ov, list):
                                    for _item in _ov:
                                        if isinstance(_item, dict):
                                            _p = _item.get("path") or _item.get("file_path") or ""
                                            if _p:
                                                _node_paths.append(_p)

                            for _d in _deliverables:
                                _ds = _del_states.get(_d.id)
                                if _ds and _ds.status == "pending":
                                    for _np in _node_paths:
                                        if _np.lower().endswith(f".{_d.format.lower()}"):
                                            _ds.status = "satisfied"
                                            _ds.matched_path = _np
                                            _ds.producing_step_id = str(_rn.id)
                                            _ds.evidence = f"node:{_rn.id}:{_np}"
                                            break
                    except Exception as _ds_err:
                        logger.debug(f"[DeliverableState] Update failed: {_ds_err}")

                # ── Progress guard ──────────────────────────────────────
                _progress_issue = self._goal_tracker.check_progress(graph)
                if _progress_issue:
                    logger.warning(f"[ProgressGuard] {_progress_issue}")
                    break

                # ── Uncovered sub-goals check ───────────────────────────
                if result.final_status == "success":
                    uncovered = self._goal_tracker.get_uncovered_sub_goals(sub_goals, graph)
                    if uncovered:
                        logger.warning(
                            f"[GoalTracker] Success but {len(uncovered)} uncovered: {uncovered}"
                        )
                        env_context = dict(env_context)
                        env_context["uncovered_sub_goals"] = uncovered
                        env_context["goal_tracker_hint"] = (
                            f"The following sub-goals are NOT yet completed: {uncovered}. "
                            f"You MUST complete them before finishing."
                        )
                        continue
                    logger.debug("[ReAct] Node(s) succeeded, continuing loop for Planner FINISH decision")

            # ── FINISH: compute final result ────────────────────────────
            if _lt_ctx is not None:
                self._lt_save_snapshot(_lt_ctx, graph, "final")

            completed = sum(1 for n in graph.nodes.values() if n.status == NodeStatus.SUCCESS)
            failed = sum(1 for n in graph.nodes.values() if n.status == NodeStatus.FAILED)
            skipped = sum(1 for n in graph.nodes.values() if n.status == NodeStatus.SKIPPED)
            final_status = self.runtime._compute_graph_status(graph)

            if _verification_passed and final_status == "failed" and completed > 0:
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
                _summary = AnswerSynthesizer.synthesize(graph, intent)
            except Exception as _synth_err:
                logger.debug(f"[GraphController] AnswerSynthesizer failed: {_synth_err}")

            _final_result = ExecutionResult(
                success=final_status in ("success", "partial_success"),
                final_status=final_status,
                completed_nodes=completed,
                failed_nodes=failed,
                skipped_nodes=skipped,
                graph=graph,
                summary=_summary,
            )
            return _final_result

        finally:
            if _final_result is not None:
                fs = _final_result.final_status
                if fs == "success":
                    _lifecycle_status = "completed"
                    if env_context.get("verification_uncertain"):
                        _result_status = "uncertain_success"
                    else:
                        _result_status = "success"
                elif fs == "partial_success":
                    _lifecycle_status = "completed"
                    _result_status = "partial_success"
                elif fs == "failed":
                    _lifecycle_status = "failed"
                    _result_status = "failed"

            _ns = NodeStatus

            try:
                from app.avatar.runtime.narrative.models import TranslationContext as _TC
                if _result_status in ("success", "partial_success"):
                    await _narrative_manager.on_event(
                        "task.completed",
                        step_id="__run__",
                        context=_TC(),
                    )
                elif _result_status in ("failed", "cancelled", "uncertain_terminal"):
                    await _narrative_manager.on_event(
                        "task.failed",
                        step_id="__run__",
                        context=_TC(
                            reason=_error_message or "任务执行失败",
                            error_message=_error_message,
                        ),
                    )
            except Exception as _ne:
                logger.debug(f"[GraphController] Narrative task lifecycle event failed: {_ne}")

            await _lifecycle.on_session_end(
                lifecycle_status=_lifecycle_status,
                result_status=_result_status,
                total_nodes=len(graph.nodes),
                completed_nodes=sum(1 for n in graph.nodes.values() if n.status == _ns.SUCCESS),
                failed_nodes=sum(1 for n in graph.nodes.values() if n.status == _ns.FAILED),
                error_message=_error_message,
            )

            if self._evolution_pipeline and _evo_trace_id:
                try:
                    from app.avatar.evolution.outcome_classifier import SubGoalResult
                    _evo_sub_goals = []

                    # Use _result_status as ground truth to prevent terminal
                    # state semantic split: if the controller decided the task
                    # succeeded (including uncertain_success), at least one
                    # sub-goal must be marked satisfied so that
                    # OutcomeClassifier won't produce FAILED for a task the
                    # controller already marked as completed.
                    _controller_says_success = _result_status in (
                        "success", "uncertain_success", "partial_success",
                    )

                    for sg in sub_goals:
                        _covered = any(
                            self._goal_tracker._node_covers(n, sg)
                            for n in graph.nodes.values()
                            if n.status == _ns.SUCCESS
                        )
                        _evo_sub_goals.append(SubGoalResult(
                            name=sg,
                            satisfied=_covered,
                        ))

                    # Reconcile: if controller says success but coverage
                    # tracker found nothing (e.g. verification was UNCERTAIN
                    # due to TargetResolver gaps), force the first sub-goal
                    # satisfied so OutcomeClassifier aligns with the
                    # controller's terminal decision.
                    if _controller_says_success and _evo_sub_goals and not any(
                        sg.satisfied for sg in _evo_sub_goals
                    ):
                        _evo_sub_goals[0].satisfied = True
                        logger.info(
                            "[GraphController] Reconciled evo sub_goals with "
                            f"_result_status={_result_status}: forced first "
                            "sub-goal satisfied to prevent terminal state split"
                        )

                    _evo_decision = (
                        f"final_status={_result_status}, "
                        f"nodes={len(graph.nodes)}, "
                        f"completed={sum(1 for n in graph.nodes.values() if n.status == _ns.SUCCESS)}, "
                        f"failed={sum(1 for n in graph.nodes.values() if n.status == _ns.FAILED)}"
                    )

                    await self._evolution_pipeline.on_task_finished_v2(
                        task_id=str(graph.id),
                        session_id=_session_id or _exec_session_id,
                        goal=intent,
                        task_type=env_context.get("task_type", "unknown"),
                        sub_goals=_evo_sub_goals,
                        decision_basis=_evo_decision,
                    )
                except Exception as _evo_err:
                    logger.debug(f"[GraphController] Evolution pipeline failed (non-blocking): {_evo_err}")

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
