"""
GraphController - Orchestration layer for graph execution

Slim orchestrator that coordinates GraphPlanner, GraphRuntime, and helper modules:
- BudgetGuard: planner budget tracking and enforcement
- DedupGuard: intent-equivalent call deduplication
- GoalTracker: goal decomposition, coverage, terminal evidence, progress guard
- DagRepairHelper: DAG auto-repair

Supports ReAct mode (iterative) and DAG mode (one-shot).
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from enum import Enum
import logging
import re
import asyncio
from datetime import datetime, timezone

from app.avatar.runtime.graph.controller.budget_guard import BudgetGuard
from app.avatar.runtime.graph.controller.dedup_guard import DedupGuard
from app.avatar.runtime.graph.controller.goal_tracker import GoalTracker
from app.avatar.runtime.graph.controller.dag_repair import DagRepairHelper

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


class _LongTaskContext:
    """
    长任务运行时上下文，封装所有长任务相关的 store/manager 引用。
    仅在 env_context 中包含 task_session_id 时激活。
    """

    def __init__(self, task_session_id: str, event_stream: Optional['TaskEventStream'] = None):
        self.task_session_id = task_session_id
        self.event_stream = event_stream
        self.graph_version = 0
        self.step_count_since_checkpoint = 0
        self.patch_count_since_snapshot = 0
        self.checkpoint_interval = 5  # 每 N 步创建 routine checkpoint
        self.snapshot_interval = 20   # 每 N 个 patch 保存 snapshot

    @staticmethod
    def from_env(env_context: dict) -> Optional['_LongTaskContext']:
        """从 env_context 中提取长任务上下文，无 task_session_id 则返回 None。"""
        tsid = env_context.get("task_session_id")
        if not tsid:
            return None
        event_stream = env_context.get("_task_event_stream")
        return _LongTaskContext(tsid, event_stream)


class GraphController:
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

        self._active_graphs: Dict[str, asyncio.Task] = {}
        self._graph_semaphore = asyncio.Semaphore(max_concurrent_graphs)

        # Helper modules (stateful per-task, reset in _execute_react_mode)
        self._budget = BudgetGuard(
            max_planner_tokens=max_planner_tokens,
            max_planner_calls=max_planner_calls,
            max_planner_cost=max_planner_cost,
        )
        self._dedup = DedupGuard()
        self._goal_tracker = GoalTracker()

        # Legacy accessor kept for backward compat (some callers read _planner_usage)
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

    # ── ReAct mode ──────────────────────────────────────────────────────

    async def _execute_react_mode(
        self,
        intent: str,
        env_context: Dict[str, Any],
        config: Dict[str, Any],
        control_handle: Optional[Any] = None,
    ) -> 'ExecutionResult':
        import time
        from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
        from app.avatar.runtime.graph.models.graph_patch import PatchOperation
        from app.avatar.runtime.graph.models.step_node import NodeStatus
        from app.avatar.runtime.graph.lifecycle.execution_lifecycle import ExecutionLifecycle
        from app.services.session_store import ExecutionSessionStore

        max_react_iterations = config.get('max_react_iterations', 200)
        max_graph_nodes = config.get('max_graph_nodes', 200)

        # ── Session setup ───────────────────────────────────────────────
        _workspace_path = env_context.get("workspace_path") or (
            str(self.guard.config.workspace_root)
            if self.guard and self.guard.config.workspace_root else ""
        )
        _policy_snap = None
        _runtime_config_snap = {
            "max_concurrent_graphs": self.max_concurrent_graphs,
            "max_planner_invocations_per_graph": self.max_planner_invocations_per_graph,
            "max_planner_tokens": self.max_planner_tokens,
            "max_planner_calls": self.max_planner_calls,
            "max_planner_cost": self.max_planner_cost,
            "max_execution_cost": self.max_execution_cost,
            "max_react_iterations": max_react_iterations,
            "max_graph_nodes": max_graph_nodes,
        }
        if self.guard:
            _policy_snap = {
                "workspace_root": str(self.guard.config.workspace_root),
                "enforce_workspace_isolation": self.guard.config.enforce_workspace_isolation,
                "default_policy": self.guard.config.default_policy,
                "max_nodes_per_patch": self.guard.config.max_nodes_per_patch,
            }
        _exec_session = ExecutionSessionStore.create(
            goal=intent,
            run_id=env_context.get("run_id"),
            task_id=env_context.get("task_id"),
            request_id=env_context.get("request_id"),
            trace_id=env_context.get("trace_id"),
            conversation_id=env_context.get("session_id"),
            workspace_path=_workspace_path,
            policy_snapshot=_policy_snap,
            runtime_config_snapshot=_runtime_config_snap,
        )
        _exec_session_id = _exec_session.id
        _lifecycle = ExecutionLifecycle(_exec_session_id)
        await _lifecycle.on_session_start()

        env_context = dict(env_context)
        env_context["exec_session_id"] = _exec_session_id

        # ── Graph + workspace ───────────────────────────────────────────
        graph = ExecutionGraph(goal=intent, nodes={}, edges={})
        graph.metadata["session_id"] = env_context.get("session_id")
        graph.metadata["env"] = env_context

        on_graph_created = env_context.get("on_graph_created")
        if on_graph_created:
            try:
                on_graph_created(str(graph.id))
            except Exception as _e:
                logger.warning(f"[GraphController] on_graph_created failed: {_e}")

        from app.avatar.runtime.graph.context.execution_context import ExecutionContext as _ExecCtx
        _session_id = env_context.get("session_id")
        _workspace = None
        _ws_session_id = _session_id or _exec_session_id
        if _ws_session_id:
            try:
                from app.avatar.runtime.workspace import get_session_workspace_manager
                _ws_mgr = get_session_workspace_manager()
                if _ws_mgr is not None:
                    _safe_session_id = _ws_session_id.replace(":", "-")
                    _workspace = _ws_mgr.get_or_create(_safe_session_id)
                    logger.debug(f"[GraphController] SessionWorkspace for {_safe_session_id}: {_workspace.root}")
            except Exception as _ws_err:
                logger.warning(f"[GraphController] SessionWorkspace failed: {_ws_err}")
        _shared_context = _ExecCtx(
            graph_id=graph.id,
            goal_desc=intent,
            inputs=env_context,
            session_id=_exec_session_id,
            task_id=graph.id,
            env=env_context,
            workspace=_workspace,
        )

        # ── Goal decomposition ──────────────────────────────────────────
        sub_goals = self._goal_tracker.decompose_goal(intent)
        logger.info(f"[GoalTracker] Decomposed '{intent}' into {len(sub_goals)} sub-goals: {sub_goals}")

        # ── Long-task runtime context ───────────────────────────────────
        _lt_ctx = _LongTaskContext.from_env(env_context)

        # ── NarrativeManager (with fallback degradation) ──────────────
        _narrative_manager: Any  # NarrativeManager | FallbackNarrativeManager
        try:
            from app.avatar.runtime.narrative.execution_narrative import NarrativeManager as _NM
            from app.avatar.runtime.narrative.narrative_mapper import NarrativeMapper as _NMapper
            from app.io.manager import SocketManager
            _socket_mgr = SocketManager.get_instance()
            _nm_mapper = _NMapper()
            _narrative_manager = _NM(
                session_id=_session_id or _exec_session_id,
                task_id=str(graph.id),
                goal=intent,
                mapper=_nm_mapper,
                socket_manager=_socket_mgr,
                sub_goals=sub_goals,
            )
        except Exception as _nm_err:
            logger.warning(f"[GraphController] NarrativeManager init failed, using fallback: {_nm_err}")
            try:
                from app.avatar.runtime.narrative.execution_narrative import FallbackNarrativeManager as _FNM
                from app.io.manager import SocketManager
                _socket_mgr = SocketManager.get_instance()
                _narrative_manager = _FNM(
                    session_id=_session_id or _exec_session_id,
                    task_id=str(graph.id),
                    socket_manager=_socket_mgr,
                )
            except Exception as _fb_err:
                logger.warning(f"[GraphController] FallbackNarrativeManager init also failed: {_fb_err}")
                from app.avatar.runtime.narrative.execution_narrative import FallbackNarrativeManager as _FNM
                _narrative_manager = _FNM(
                    session_id=_session_id or _exec_session_id,
                    task_id=str(graph.id),
                )

        # ── Per-task state reset ────────────────────────────────────────
        planner_invocations = 0
        _handle = control_handle
        _consecutive_failures = 0
        _MAX_CONSECUTIVE_FAILURES = 3

        _is_simple = env_context.get("simple_task_mode", False)
        self._budget.reset(simple_task_mode=_is_simple)
        self._planner_usage = self._budget._usage  # keep legacy ref in sync
        self._goal_tracker.reset()

        _lifecycle_status = "failed"
        _result_status = "unknown"
        _error_message: Optional[str] = None
        _final_result: Optional['ExecutionResult'] = None
        _verification_passed = False  # Set True when VerificationGate verdict=PASS

        # ── Evolution trace (if pipeline wired) ─────────────────────────
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
                    # Long-task: save final snapshot on cancel
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

                # ── Budget check (BudgetGuard) ──────────────────────────
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

                # ── Terminal evidence short-circuit (GoalTracker) ───────
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
                patch = await self.planner.plan_next_step(graph, env_context)
                _plan_latency_ms = int((time.monotonic() - _plan_start) * 1000)

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

                    # ── Verification Gate ───────────────────────────────
                    # Long-task: run DeliveryGate before verification
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

                    # If VerificationGate returned break_pass (or was not invoked
                    # but all sub-goals are covered), mark verification as passed
                    # so the final status computation can override historical
                    # node-level failures that were recovered from.
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

                # ── Dedup + Apply patch ─────────────────────────────────
                patch = self._dedup.deduplicate_patch(patch, graph)
                if patch is None:
                    # All new nodes were duplicates. Give Planner ONE
                    # replan chance with a hint before terminating.
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

                self._apply_patch(patch, graph, lt_ctx=_lt_ctx)
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

                # ── Execute ready nodes ─────────────────────────────────
                result = await self.runtime.execute_ready_nodes(graph, context=_shared_context)

                # ── Evolution: record completed/failed nodes as steps ───
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
                            continue  # Only emit events for nodes we started this iteration
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
                            # Check for artifacts
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
                            # Emit retry.triggered if the node can still retry
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

                # ── Long-task: routine checkpoint every N steps ─────
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

                # ── Circuit breaker (consecutive failures) ──────────────
                if result.final_status in ("failed", "partial_success"):
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
                else:
                    _consecutive_failures = 0

                # ── Progress guard (GoalTracker) ────────────────────────
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
            # Long-task: save final snapshot
            if _lt_ctx is not None:
                self._lt_save_snapshot(_lt_ctx, graph, "final")

            completed = sum(1 for n in graph.nodes.values() if n.status == NodeStatus.SUCCESS)
            failed = sum(1 for n in graph.nodes.values() if n.status == NodeStatus.FAILED)
            skipped = sum(1 for n in graph.nodes.values() if n.status == NodeStatus.SKIPPED)
            final_status = self.runtime._compute_graph_status(graph)

            # ── Recovery override: VerificationGate PASS trumps historical failures ──
            # When the ReAct loop recovered (e.g. step_1 failed, Planner retried
            # with step_2 which succeeded, VerificationGate confirmed goal achieved),
            # _compute_graph_status still sees the historical failed node and returns
            # "failed". Override to "success" because the goal was verified as met.
            if _verification_passed and final_status == "failed" and completed > 0:
                logger.info(
                    f"[GraphController] Recovery override: VerificationGate PASS with "
                    f"{completed} succeeded / {failed} historically-failed node(s) "
                    f"→ final_status overridden from 'failed' to 'success'"
                )
                final_status = "success"

            from app.avatar.runtime.graph.runtime.graph_runtime import ExecutionResult
            _final_result = ExecutionResult(
                success=final_status in ("success", "partial_success"),
                final_status=final_status,
                completed_nodes=completed,
                failed_nodes=failed,
                skipped_nodes=skipped,
                graph=graph,
            )
            return _final_result

        finally:
            if _final_result is not None:
                fs = _final_result.final_status
                if fs == "success":
                    _lifecycle_status = "completed"
                    _result_status = "success"
                elif fs == "partial_success":
                    _lifecycle_status = "completed"
                    _result_status = "partial_success"
                elif fs == "failed":
                    _lifecycle_status = "failed"
                    _result_status = "failed"

            _ns = NodeStatus

            # ── Narrative: task.completed / task.failed ──────────────────
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

            # ── Evolution pipeline (fire-and-forget) ────────────────────
            if self._evolution_pipeline and _evo_trace_id:
                try:
                    # Build SubGoalResult list from GoalTracker sub_goals + graph
                    from app.avatar.evolution.outcome_classifier import SubGoalResult
                    _evo_sub_goals = []
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

        # ── Evolution trace (if pipeline wired) ─────────────────────────
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
            # ── Evolution pipeline (fire-and-forget) ────────────────────
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

    # ── Patch application ───────────────────────────────────────────────

    _STEP_REF_PATTERN = re.compile(r'step_(\d+)_output')

    def _apply_patch(self, patch: 'GraphPatch', graph: 'ExecutionGraph', lt_ctx: Optional['_LongTaskContext'] = None) -> None:
        from app.avatar.runtime.graph.models.graph_patch import PatchOperation
        for action in patch.actions:
            if action.operation == PatchOperation.ADD_NODE and action.node:
                graph.add_node(action.node)
                logger.debug(f"Added node: {action.node.id}")
                self._inject_implicit_edges(action.node, graph)
            elif action.operation == PatchOperation.ADD_EDGE and action.edge:
                graph.add_edge(action.edge)
                logger.debug(f"Added edge: {action.edge.source_node} → {action.edge.target_node}")
            elif action.operation == PatchOperation.REMOVE_NODE and action.node_id:
                if action.node_id in graph.nodes:
                    del graph.nodes[action.node_id]
                    logger.debug(f"Removed node: {action.node_id}")
            elif action.operation == PatchOperation.REMOVE_EDGE and action.edge_id:
                if action.edge_id in graph.edges:
                    del graph.edges[action.edge_id]
                    logger.debug(f"Removed edge: {action.edge_id}")
            elif action.operation == PatchOperation.FINISH:
                logger.debug("FINISH operation in patch")

            # Long-task: record each action as a PatchLogEntry
            if lt_ctx is not None and action.operation != PatchOperation.FINISH:
                lt_ctx.graph_version += 1
                self._lt_record_patch(lt_ctx, action, graph)

        logger.info(
            f"Applied patch: {len(patch.actions)} actions, "
            f"graph now has {len(graph.nodes)} nodes, {len(graph.edges)} edges"
        )

    # Ordered priority list for resolving the "primary output" field of a skill.
    # Must stay in sync with _inject_node_outputs_into_code in GraphExecutor.
    _PRIMARY_OUTPUT_FIELDS = ("output", "result", "content", "stdout")

    @staticmethod
    def _infer_primary_output_field(source_node: 'StepNode') -> str:
        """
        Infer the best source_field for an AutoEdge by inspecting the source
        node's skill output_model via the registry.

        Resolution order (first match wins):
        1. Walk _PRIMARY_OUTPUT_FIELDS against the skill's output_model fields.
        2. If the source node already has outputs (completed), walk the same
           priority list against actual output keys.
        3. Fallback to "output" (the most common convention).
        """
        # --- Phase 1: static schema inspection ---
        try:
            from app.avatar.skills.registry import skill_registry
            skill_cls = skill_registry.get(source_node.capability_name)
            if skill_cls is not None:
                model_fields = set(skill_cls.spec.output_model.model_fields.keys())
                for candidate in GraphController._PRIMARY_OUTPUT_FIELDS:
                    if candidate in model_fields:
                        return candidate
        except Exception:
            pass  # registry not ready or import issue — fall through

        # --- Phase 2: runtime outputs (node already completed) ---
        if source_node.outputs:
            for candidate in GraphController._PRIMARY_OUTPUT_FIELDS:
                if candidate in source_node.outputs:
                    return candidate

        # --- Phase 3: convention fallback ---
        return "output"

    def _inject_implicit_edges(self, node: 'StepNode', graph: 'ExecutionGraph') -> None:
        """Scan node params for step_N_output references and add data edges.

        Parameters listed in the target skill's ``SkillSpec.code_params`` are
        skipped because they contain executable code where ``step_N_output``
        tokens are variable names injected at runtime (by
        ``_inject_node_outputs_into_code``), not template placeholders for
        DataEdge substitution.
        """
        if not node.params:
            return
        try:
            from app.avatar.runtime.graph.models.data_edge import DataEdge

            # Determine which params are code-bearing via skill metadata
            skip_params: set = set()
            try:
                from app.avatar.skills.registry import skill_registry
                skill_cls = skill_registry.get(node.capability_name)
                if skill_cls is not None:
                    skip_params = skill_cls.spec.code_params
            except Exception:
                pass

            for param_name, param_value in node.params.items():
                if param_name in skip_params:
                    continue
                if not isinstance(param_value, str):
                    continue
                for match in self._STEP_REF_PATTERN.finditer(param_value):
                    source_node_id = f"step_{match.group(1)}"
                    source_node = graph.nodes.get(source_node_id)
                    if source_node is None:
                        continue
                    existing = any(
                        e.source_node == source_node_id and
                        e.target_node == node.id and
                        e.target_param == param_name
                        for e in graph.edges.values()
                    )
                    if existing:
                        continue
                    source_field = self._infer_primary_output_field(source_node)
                    edge = DataEdge(
                        source_node=source_node_id,
                        source_field=source_field,
                        target_node=node.id,
                        target_param=param_name,
                    )
                    graph.add_edge(edge)
                    logger.info(f"[AutoEdge] {source_node_id} → {node.id}.{param_name} (field={source_field})")
        except Exception as e:
            logger.debug(f"[AutoEdge] Failed for {node.id}: {e}")

    # ── Event emission ──────────────────────────────────────────────────

    def _emit_plan_generated(self, graph: 'ExecutionGraph', env_context: Dict[str, Any]) -> None:
        """Emit plan.generated event for frontend progress display."""
        if not self.runtime.event_bus:
            return
        try:
            from app.avatar.runtime.events.types import Event, EventType
            nodes = list(graph.nodes.values())
            steps = [
                {
                    "id": str(n.id),
                    "skill": n.capability_name,
                    "skill_name": n.capability_name,
                    "description": (n.metadata or {}).get("description") or n.capability_name.replace(".", " → "),
                    "status": "pending",
                    "order": i,
                    "params": n.params or {},
                    "depends_on": [],
                }
                for i, n in enumerate(nodes)
            ]
            event = Event(
                type=EventType.PLAN_GENERATED,
                source="graph_controller",
                payload={
                    "session_id": env_context.get("session_id", ""),
                    "plan": {"id": graph.id, "goal": graph.goal, "steps": steps},
                },
            )
            self.runtime.event_bus.publish(event)
        except Exception as e:
            logger.warning(f"[GraphController] Failed to emit plan.generated: {e}")

    # ── Narrative helper functions ──────────────────────────────────────

    @staticmethod
    def _summarize_params(params: Optional[Dict[str, Any]]) -> Optional[str]:
        """Summarize node params into a short string for narrative context.

        Extracts the most meaningful parameter (file paths, queries, etc.)
        and returns a concise summary.  Returns None when params are empty.
        """
        if not params:
            return None
        # Priority: look for common meaningful keys
        for key in ("file", "path", "filename", "file_path", "url", "query", "code_path", "target"):
            val = params.get(key)
            if val and isinstance(val, str):
                # Extract basename for paths
                if "/" in val or "\\" in val:
                    return val.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
                return val[:60]
        # Fallback: first string value
        for val in params.values():
            if isinstance(val, str) and val.strip():
                return val[:60]
        return None

    @staticmethod
    def _summarize_output(node: Any) -> Optional[str]:
        """Summarize node outputs into a short string for narrative context."""
        if not node.outputs:
            return None
        # Look for common output keys
        for key in ("result", "summary", "output", "content", "message"):
            val = node.outputs.get(key)
            if val and isinstance(val, str):
                return val[:80]
        # Fallback: first string value
        for val in node.outputs.values():
            if isinstance(val, str) and val.strip():
                return val[:80]
        return None

    @staticmethod
    def _get_semantic_label(node: Any) -> Optional[str]:
        """Extract semantic_label from node metadata/output_contract."""
        if not node.metadata:
            return None
        # Check output_contract for semantic_label
        oc = node.metadata.get("output_contract")
        if oc is not None:
            if isinstance(oc, dict):
                label = oc.get("semantic_label")
            else:
                label = getattr(oc, "semantic_label", None)
            if label:
                return str(label)
        # Check description in metadata
        desc = node.metadata.get("description")
        if desc and isinstance(desc, str):
            return desc
        return None

    # ── Verification gate ───────────────────────────────────────────────

    async def _run_verification_gate(
        self,
        intent: str,
        graph: 'ExecutionGraph',
        workspace: Optional[Any],
        env_context: Dict[str, Any],
        session_id: str,
        task_context: Optional[Any],
    ) -> str:
        """
        Run CompletionGate at FINISH decision point.
        Returns: "break_pass", "continue", "break_partial", "break_failed", "break_uncertain".
        """
        try:
            from app.avatar.runtime.verification.goal_normalizer import GoalNormalizer
            from app.avatar.runtime.verification.target_resolver import TargetResolver
            from app.avatar.runtime.verification.goal_coverage_tracker import GoalCoverageTracker
            from app.avatar.runtime.verification.completion_gate import CompletionGate
            from app.avatar.runtime.verification.repair_loop import RepairLoop
            from app.avatar.runtime.verification.verifier_registry import VerifierRegistry
            from app.avatar.runtime.verification.models import GateVerdict, RiskLevel
            from app.avatar.runtime.graph.storage.step_trace_store import StepTraceStore
        except ImportError as e:
            logger.warning(f"[VerificationGate] Import failed, skipping: {e}")
            return "break_pass"

        if workspace is None:
            logger.debug("[VerificationGate] No workspace, skipping")
            return "break_pass"

        try:
            _normalizer = GoalNormalizer()
            if "normalized_goal" not in env_context:
                env_context["normalized_goal"] = _normalizer.normalize(intent)
            normalized_goal = env_context["normalized_goal"]

            _resolver = TargetResolver()
            targets = _resolver.resolve_targets(normalized_goal, graph, workspace)
            env_context["verification_targets"] = targets

            _tracker = GoalCoverageTracker(_normalizer)
            if "goal_coverage_summary" not in env_context:
                env_context["goal_coverage_summary"] = _tracker.initialize(normalized_goal)
            coverage_summary = _tracker.update_after_round(
                env_context["goal_coverage_summary"], graph, workspace
            )
            env_context["goal_coverage_summary"] = coverage_summary
            env_context["goal_coverage_hint"] = coverage_summary.to_planner_hint()

            _trace_store = StepTraceStore()
            _registry = VerifierRegistry()
            _gate = CompletionGate(_registry, _trace_store)
            decision = await _gate.evaluate(
                normalized_goal=normalized_goal,
                targets=targets,
                graph=graph,
                workspace=workspace,
                coverage_summary=coverage_summary,
                session_id=session_id,
            )

            logger.info(
                f"[VerificationGate] verdict={decision.verdict} "
                f"passed={decision.passed_count} failed={decision.failed_count} "
                f"trace_hole={decision.trace_hole}"
            )

            if decision.verdict == GateVerdict.PASS:
                return "break_pass"

            if decision.verdict == GateVerdict.FAIL:
                repair_state = env_context.get("_repair_state")
                if repair_state is None:
                    from app.avatar.runtime.core.context import RepairState
                    repair_state = RepairState(max_attempts=3)
                    env_context["_repair_state"] = repair_state

                _repair_loop = RepairLoop(
                    _trace_store,
                    artifact_registry=env_context.get("artifact_registry"),
                )
                repair_feedback = _repair_loop.trigger_repair(
                    failed_results=decision.failed_results,
                    graph=graph,
                    repair_state=repair_state,
                    session_id=session_id,
                )

                if repair_feedback.context_patch.get("repair_exhausted"):
                    has_any_pass = decision.passed_count > 0
                    terminal_state = "partial_success" if has_any_pass else "repair_exhausted"
                    try:
                        _trace_store.record_event(
                            session_id=session_id,
                            task_id=env_context.get("task_id", ""),
                            step_id="",
                            event_type="task_terminal",
                            payload={
                                "terminal_state": terminal_state,
                                "reason": "repair_exhausted",
                                "verification_summary": {
                                    "passed": decision.passed_count,
                                    "failed": decision.failed_count,
                                },
                                "repair_history_summary": repair_feedback.to_planner_summary(),
                            },
                        )
                    except Exception:
                        pass
                    return "break_partial" if has_any_pass else "break_failed"

                env_context["repair_feedback"] = repair_feedback
                env_context["repair_feedback_summary"] = repair_feedback.to_planner_summary()
                env_context["verification_failed_hints"] = repair_feedback.repair_hints
                return "continue"

            if decision.verdict == GateVerdict.UNCERTAIN:
                if normalized_goal.risk_level == RiskLevel.HIGH:
                    return "break_uncertain"
                return "break_pass"

        except Exception as exc:
            logger.warning(f"[VerificationGate] Error, allowing FINISH: {exc}", exc_info=True)
        return "break_pass"

    # ── Legacy API ──────────────────────────────────────────────────────

    def get_planner_usage(self) -> Dict[str, Any]:
        """Get current planner usage statistics."""
        return self._budget.get_usage()

    # ── Long-task runtime helpers ───────────────────────────────────────

    async def _lt_persist_step_results(
        self, graph: 'ExecutionGraph', lt_ctx: '_LongTaskContext'
    ) -> None:
        """
        持久化步骤执行结果到 StepStateStore + ArtifactStore。

        有产物分支：注册产物 → 建立依赖 → stale 传播 → 更新步骤状态
        无产物分支：仅更新步骤状态和 side_effect_summary
        """
        try:
            from app.services.step_state_store import StepStateStore
            from app.services.artifact_store import ArtifactStore
            from app.avatar.runtime.graph.models.step_node import NodeStatus
            from app.db.long_task_models import StepState
            import json
            import hashlib

            for node in graph.nodes.values():
                if node.status not in (NodeStatus.SUCCESS, NodeStatus.FAILED):
                    continue

                # Check if already persisted (avoid double-write)
                existing = StepStateStore.get(str(node.id))
                if existing and existing.status == node.status.value:
                    continue

                # Build StepState record
                step_state = StepState(
                    id=str(node.id),
                    task_session_id=lt_ctx.task_session_id,
                    graph_version=lt_ctx.graph_version,
                    status=node.status.value,
                    capability_name=node.capability_name,
                    input_snapshot_json=json.dumps(node.params, ensure_ascii=False) if node.params else None,
                    output_json=json.dumps(node.result, ensure_ascii=False) if hasattr(node, 'result') and node.result else None,
                )
                StepStateStore.upsert(step_state)

                # Artifact registration (有产物分支)
                if node.status == NodeStatus.SUCCESS:
                    output_contract = node.metadata.get("output_contract") if node.metadata else None
                    if output_contract:
                        artifacts = output_contract if isinstance(output_contract, list) else [output_contract]
                        for art in artifacts:
                            if isinstance(art, dict) and art.get("path"):
                                content = json.dumps(art, ensure_ascii=False)
                                content_hash = hashlib.sha256(content.encode()).hexdigest()
                                ArtifactStore.register_artifact(
                                    task_session_id=lt_ctx.task_session_id,
                                    artifact_path=art["path"],
                                    artifact_kind=art.get("kind", "file"),
                                    producer_step_id=str(node.id),
                                    content_hash=content_hash,
                                    size=len(content),
                                    mtime=0.0,
                                )
                    # else: 无产物分支 — 仅步骤状态已更新

        except Exception as e:
            logger.warning(f"[GraphController] Long-task step persist failed: {e}")

    async def _lt_create_routine_checkpoint(self, lt_ctx: '_LongTaskContext') -> None:
        """创建 routine 级别 checkpoint。"""
        try:
            from app.services.checkpoint_store import CheckpointStore
            from app.services.step_state_store import StepStateStore
            from app.services.plan_graph_store import PlanGraphStore
            from app.avatar.runtime.graph.managers.checkpoint_manager import CheckpointManager

            cp_mgr = CheckpointManager(
                CheckpointStore, StepStateStore, PlanGraphStore,
                event_stream=lt_ctx.event_stream,
            )
            await cp_mgr.create_checkpoint(
                task_session_id=lt_ctx.task_session_id,
                importance="routine",
                reason=f"periodic:step_count",
            )
        except Exception as e:
            logger.warning(f"[GraphController] Routine checkpoint failed (non-fatal): {e}")

    def _lt_record_patch(
        self, lt_ctx: '_LongTaskContext', action, graph: 'ExecutionGraph'
    ) -> None:
        """记录 PatchLogEntry 并在达到阈值时保存 snapshot。"""
        try:
            from app.services.plan_graph_store import PlanGraphStore
            import json

            operation = action.operation.value if hasattr(action.operation, 'value') else str(action.operation)
            params = {}
            if action.node:
                params["node_id"] = str(action.node.id)
                params["capability"] = action.node.capability_name
            elif action.node_id:
                params["node_id"] = action.node_id
            elif action.edge:
                params["source"] = action.edge.source_node
                params["target"] = action.edge.target_node

            PlanGraphStore.append_patch(
                task_session_id=lt_ctx.task_session_id,
                graph_version=lt_ctx.graph_version,
                operation=operation,
                operation_params_json=json.dumps(params, ensure_ascii=False),
                change_reason="initial_plan",
                change_source="planner",
            )

            # Periodic snapshot + initial plan snapshot
            lt_ctx.patch_count_since_snapshot += 1
            if lt_ctx.graph_version == 1:
                # First patch — save initial plan snapshot
                self._lt_save_snapshot(lt_ctx, graph, "initial_plan")
                lt_ctx.patch_count_since_snapshot = 0
            elif lt_ctx.patch_count_since_snapshot >= lt_ctx.snapshot_interval:
                self._lt_save_snapshot(lt_ctx, graph, "periodic")
                lt_ctx.patch_count_since_snapshot = 0

        except Exception as e:
            logger.warning(f"[GraphController] Patch log recording failed: {e}")

    def _lt_save_snapshot(
        self, lt_ctx: '_LongTaskContext', graph: 'ExecutionGraph', reason: str
    ) -> None:
        """保存 PlanGraphSnapshot。"""
        try:
            from app.services.plan_graph_store import PlanGraphStore
            import json

            graph_data = {
                "goal": graph.goal,
                "nodes": {
                    nid: {
                        "id": str(n.id),
                        "capability_name": n.capability_name,
                        "status": n.status.value if hasattr(n.status, 'value') else str(n.status),
                        "params": n.params,
                    }
                    for nid, n in graph.nodes.items()
                },
                "edges": {
                    eid: {
                        "source": e.source_node,
                        "target": e.target_node,
                    }
                    for eid, e in graph.edges.items()
                },
            }
            PlanGraphStore.save_snapshot(
                task_session_id=lt_ctx.task_session_id,
                graph_version=lt_ctx.graph_version,
                graph_json=json.dumps(graph_data, ensure_ascii=False),
                snapshot_reason=reason,
                change_source="system",
            )
        except Exception as e:
            logger.warning(f"[GraphController] Snapshot save failed: {e}")

    async def _lt_run_delivery_gate(self, lt_ctx: '_LongTaskContext') -> Optional[dict]:
        """运行 DeliveryGate 检查。"""
        try:
            from app.avatar.runtime.graph.managers.delivery_gate import DeliveryGate
            from app.avatar.runtime.graph.artifact_dep_graph import ArtifactDependencyGraph
            from app.services.step_state_store import StepStateStore

            dep_graph = ArtifactDependencyGraph(event_stream=lt_ctx.event_stream)
            gate = DeliveryGate(dep_graph, StepStateStore, event_stream=lt_ctx.event_stream)
            return await gate.evaluate(lt_ctx.task_session_id)
        except Exception as e:
            logger.warning(f"[GraphController] DeliveryGate check failed: {e}")
            return None
