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

from app.avatar.runtime.graph.controller.guards.budget_guard import BudgetGuard
from app.avatar.runtime.graph.controller.guards.dedup_guard import DedupGuard
from app.avatar.runtime.graph.controller.guards.goal_tracker import GoalTracker
from app.avatar.runtime.graph.controller.synthesis.dag_repair import DagRepairHelper
from app.avatar.runtime.graph.controller.execution.edge_manager import EdgeManagerMixin
from app.avatar.runtime.graph.controller.execution.fan_node_executor import FanNodeExecutorMixin
from app.avatar.runtime.graph.controller.events.event_emitter import EventEmitterMixin
from app.avatar.runtime.graph.controller.guards.verification_gate import VerificationGateMixin
from app.avatar.runtime.graph.controller.persistence.long_task_helpers import LongTaskContext, LongTaskMixin
from app.avatar.runtime.graph.controller.persistence.durable_state_mixin import DurableContext, DurableStateMixin
from app.avatar.runtime.graph.controller.persistence.durable_interrupt import DurableInterruptSignal
from app.avatar.runtime.graph.controller.react.react_setup import ReactSetupMixin
from app.avatar.runtime.graph.controller.react.react_finish_handler import ReactFinishHandlerMixin
from app.avatar.runtime.graph.controller.react.recovery_handler import RecoveryHandlerMixin
from app.avatar.runtime.graph.controller.react.react_post_execution import ReactPostExecutionMixin
from app.avatar.runtime.graph.controller.react.react_finalizer import ReactFinalizerMixin
from app.avatar.runtime.graph.controller.react.react_state import ReactLoopState
from app.avatar.runtime.graph.controller.react.react_guards import ReactGuardsMixin
from app.avatar.runtime.graph.controller.execution.dag_executor import DAGExecutorMixin
from app.avatar.runtime.graph.controller.execution.multi_agent_executor import (
    MultiAgentExecutorMixin, _parse_worker_feedback, _strip_feedback_tag,
)

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.graph.planner.graph_planner import GraphPlanner
    from app.avatar.runtime.graph.runtime.graph_runtime import GraphRuntime, ExecutionResult
    from app.avatar.runtime.graph.guard.planner_guard import PlannerGuard
    from app.avatar.runtime.graph.events.task_event_stream import TaskEventStream
    from app.avatar.evolution.pipeline import EvolutionPipeline

logger = logging.getLogger(__name__)


# ── Configurable hint templates ─────────────────────────────────────

class ControllerHints:
    """Planner hint strings used by DirectReplyGuard and ContinuousTaskRouter.

    Centralised here so they can be overridden without modifying control flow.
    """

    # DirectReplyGuard: injected when Planner tries to FINISH with a
    # direct reply for an action intent. {skill_hint} is filled at runtime.
    DIRECT_REPLY_BLOCKED = (
        "You MUST execute this task, not just explain it. "
        "The user wants you to PERFORM the action, not describe how. "
        "Use the appropriate skills to carry out the request.{skill_hint}"
    )

    # Skill-aware suffix for DIRECT_REPLY_BLOCKED.
    # {skills} = comma-separated available desktop skill names.
    SKILL_HINT_SUFFIX = (
        " Available skills for this task: {skills}."
        " You MUST use one of these skills, NOT llm.fallback."
    )

    # ContinuousTaskRouter: injected when a continuous/scheduled task is detected.
    CONTINUOUS_TASK = (
        "This is a CONTINUOUS/SCHEDULED task (loop, repeat, periodic). "
        "IMPORTANT: Do NOT use python.run to implement timers or loops — "
        "sandbox containers have strict timeouts and will be killed. "
        "Instead, execute the action ONCE using the appropriate skill "
        "(e.g. computer.mouse.scroll, computer.keyboard.press for desktop ops). "
        "The runtime scheduling system will handle the repetition interval. "
        "Your job is to plan the SINGLE action that should be repeated."
    )

    # Capability gap early-exit default message
    CAPABILITY_GAP_DEFAULT = "能力不可用"


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
    DurableStateMixin,
    ReactSetupMixin,
    ReactFinishHandlerMixin,
    RecoveryHandlerMixin,
    ReactPostExecutionMixin,
    ReactFinalizerMixin,
    ReactGuardsMixin,
    DAGExecutorMixin,
    MultiAgentExecutorMixin,
):
    """
    Orchestration layer for graph execution.

    Coordinates GraphPlanner, PlannerGuard, GraphRuntime, and helper modules.
    Supports ReAct (iterative) and DAG (one-shot) execution modes.
    """

    # 节点类型 → 角色分派表 (属性 22)
    _ROLE_DISPATCH_TABLE: Dict[str, str] = {
        "planner_node": "planner",
        "research_node": "researcher",
        "verification_node": "verifier",
        "recovery_node": "recovery",
        "synthesis_node": "supervisor",
        "standard": "executor",
    }

    @classmethod
    def register_role_dispatch(cls, node_type: str, role: str) -> None:
        """运行时注册新的节点类型到角色映射."""
        cls._ROLE_DISPATCH_TABLE[node_type] = role

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

        # TaskExecutionPlan: structured execution layer for complex tasks
        # Replaces PhasedPlanner as primary path; PhasedPlanner kept as fallback
        self._plan_builder: Optional[Any] = None
        self._plan_executor: Optional[Any] = None
        try:
            from app.avatar.runtime.task.plan_builder import TaskExecutionPlanBuilder
            from app.avatar.runtime.task.plan_executor import TaskPlanExecutor
            self._plan_builder = TaskExecutionPlanBuilder(llm_client=None)
            self._plan_executor = TaskPlanExecutor()
        except Exception as _tep_err:
            logger.warning("[GraphController] TaskExecutionPlan init failed: %s", _tep_err)

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

        # ── Capability gap early-exit ───────────────────────────────────
        # If VisionGate detected that the task requires capabilities that
        # are not available, return a direct reply immediately instead of
        # letting Planner misinterpret the task.
        _cap_gap = s.env_context.get("_capability_gap")
        if _cap_gap:
            from app.avatar.runtime.graph.runtime.graph_runtime import ExecutionResult
            _gap_msg = s.env_context.get("_capability_gap_message", ControllerHints.CAPABILITY_GAP_DEFAULT)
            logger.info(
                "[CapabilityGap] Early exit: %s — %s", _cap_gap, _gap_msg[:80],
            )
            s.direct_reply = _gap_msg
            s.lifecycle_status = "completed"
            s.result_status = "success"
            s.final_result = ExecutionResult(
                success=True,
                final_status="success",
                graph=s.graph,
            )
            return s.final_result

        # ── Gate waiting early-exit ─────────────────────────────────────
        # If ClarificationEngine created a persistent gate, end this
        # execution round. Session should transition to WAITING_INPUT.
        if s.env_context.get("_gate_waiting"):
            from app.avatar.runtime.graph.runtime.graph_runtime import ExecutionResult
            _gate_ctx = s.env_context.get("_gate_context", {})
            logger.info(
                "[GateRuntime] Execution round ending: gate %s active",
                _gate_ctx.get("gate_id", "?"),
            )
            s.lifecycle_status = "waiting_input"
            s.result_status = "waiting_input"
            s.final_result = ExecutionResult(
                success=False,
                final_status="waiting_input",
                graph=s.graph,
                summary=f"Execution paused: waiting for user input (gate {_gate_ctx.get('gate_id', '?')})",
            )
            return s.final_result

        # ── Continuous/scheduled task detection ──────────────────────────
        # Detect loop/scheduled patterns early so Planner and LongTask
        # runtime can handle them properly instead of treating them as
        # one-shot tasks that FINISH after a single direct reply.
        from app.avatar.runtime.task.intent_classifier import classify_intent as _ci
        _early_signals = _ci(intent)
        if _early_signals.task_kind.value == "continuous_loop":
            s.env_context = dict(s.env_context)
            s.env_context["_continuous_task"] = True
            s.env_context["_task_kind"] = "continuous_loop"
            s.env_context["goal_tracker_hint"] = ControllerHints.CONTINUOUS_TASK
            # Force long-task context activation for continuous tasks
            if not s.env_context.get("_long_task_enabled"):
                s.env_context["_long_task_enabled"] = True
            logger.info(
                "[ContinuousTaskRouter] Detected continuous task: %s",
                intent[:80],
            )
        elif _early_signals.task_kind.value != "general":
            # Inject task_kind for all classified intents
            s.env_context = dict(s.env_context)
            s.env_context["_task_kind"] = _early_signals.task_kind.value

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

        # ── Durable state machine context ───────────────────────────────
        # 灰度路由：根据 DurableStateConfig 决定是否激活 durable_ctx
        from app.config.durable_state_config import get_durable_config
        _durable_cfg = get_durable_config()
        if _durable_cfg.enabled:
            s.durable_ctx = DurableContext.from_env(s.env_context)
            if s.durable_ctx:
                self._start_heartbeat(s.durable_ctx)
        else:
            s.durable_ctx = None

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
                    task_type=s.env_context.get("_task_kind") or s.env_context.get("task_type", "unknown"),
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
                    # BUT only for pure explanation/query intents. Action intents
                    # (desktop control, file ops, time loops) must enter execution
                    # or be explicitly rejected — never silently "completed".
                    if _direct_msg and len(s.graph.nodes) == 0:
                        from app.avatar.runtime.task.intent_classifier import classify_intent
                        _intent_signals = classify_intent(intent)
                        if _intent_signals.requires_execution:
                            logger.warning(
                                "[DirectReplyGuard] Blocked direct-reply FINISH for "
                                "action intent (patterns=%s). Forcing re-plan.",
                                _intent_signals.matched_patterns,
                            )
                            s.env_context = dict(s.env_context)
                            s.env_context["_direct_reply_blocked"] = True
                            s.env_context["_intent_signals"] = {
                                "task_kind": _intent_signals.task_kind.value,
                                "patterns": _intent_signals.matched_patterns,
                            }
                            # Build skill-aware hint so Planner knows exactly
                            # which skills to use instead of falling back to
                            # llm.fallback or generic explanations.
                            _cap_ctx = s.env_context.get("_capability_context") or {}
                            _desktop_skills = _cap_ctx.get("available_desktop_skills", [])
                            _avail_skills = s.env_context.get("available_skills")
                            if not _desktop_skills and isinstance(_avail_skills, dict):
                                # Fallback: extract desktop-related skills from registry
                                _prefixes = self._react_setup_config.desktop_skill_prefixes
                                _desktop_skills = [
                                    k for k in _avail_skills
                                    if any(k.startswith(pfx) for pfx in _prefixes)
                                ]
                            _skill_hint = ""
                            if _desktop_skills:
                                _skill_hint = ControllerHints.SKILL_HINT_SUFFIX.format(
                                    skills=", ".join(_desktop_skills),
                                )
                            s.env_context["goal_tracker_hint"] = (
                                ControllerHints.DIRECT_REPLY_BLOCKED.format(
                                    skill_hint=_skill_hint,
                                )
                            )
                            # Don't break — continue the loop so Planner re-plans
                            continue

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
                        # CRITICAL: transition session planned → running before
                        # returning, so _finalize_react_session can do
                        # running → completed/failed legally.  Without this the
                        # session stays at "planned" and on_session_end falls
                        # back to "failed" because planned → completed is invalid.
                        await s.lifecycle.on_execution_started()
                        s.final_result = _routed
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

                # ── Durable: after-step hook ────────────────────────────
                if s.durable_ctx is not None:
                    from app.avatar.runtime.graph.models.step_node import NodeStatus as _DurNS
                    for _dn in s.graph.nodes.values():
                        if _dn.id in s.pending_node_ids and _dn.status == _DurNS.SUCCESS:
                            _output_digest = str(hash(str(getattr(_dn, 'result', ''))))
                            await self._durable_after_step(str(_dn.id), _output_digest, s.durable_ctx)

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

        except DurableInterruptSignal as _dis:
            # Durable interrupt: 审批等待/暂停 — 安全退出执行循环
            logger.info(f"[GraphController] DurableInterrupt: {_dis.reason}")
            s.lifecycle_status = "interrupted"
            s.result_status = _dis.reason
            s.final_result = self._compute_final_result(s, intent)
            return s.final_result

        finally:
            # Cancel background task understanding if still pending
            if not _task_understanding_resolved and not _task_understanding_task.done():
                _task_understanding_task.cancel()
            # Stop durable heartbeat if active
            if s.durable_ctx is not None:
                self._stop_heartbeat(s.durable_ctx)
            await self._finalize_react_session(s)

    # ── DAG mode (delegated to DAGExecutorMixin) ──────────────────────
    # ── Multi-Agent mode (delegated to MultiAgentExecutorMixin) ─────
