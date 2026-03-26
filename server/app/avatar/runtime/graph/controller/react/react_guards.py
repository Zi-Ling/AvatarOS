"""
ReactGuardsMixin – cancellation, iteration limits, self-monitoring,
complexity routing, fan-node execution, and final-result computation
helpers extracted from GraphController.

These methods are mixed back into GraphController via multiple inheritance.
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from app.avatar.runtime.graph.controller.react.react_state import ReactLoopState
    from app.avatar.runtime.graph.runtime.graph_runtime import ExecutionResult

logger = logging.getLogger(__name__)


class ReactGuardsMixin:
    """Cancellation, iteration-limit, self-monitor, complexity-routing,
    fan-node execution, and final-result helpers for the ReAct loop."""

    # ── Depth / Budget constants ────────────────────────────────────
    # depth=0 top-level: allows multi-agent + PhasedPlanner + BatchPlan
    # depth=1 subtask: react iterations only, no multi-agent / PhasedPlanner
    # depth>=2 grandchild: simple execution, max_iterations greatly reduced
    MAX_EXECUTION_DEPTH = 2
    DEEP_SUBTASK_MAX_ITERATIONS = 15
    SUBTASK_MAX_ITERATIONS = 50

    # Force-terminate after stuck threshold + this many extra ticks
    _STUCK_FORCE_TERMINATE_EXTRA = 3

    # ── Cancellation ────────────────────────────────────────────────

    def _check_cancellation(self, s: 'ReactLoopState') -> Optional['ExecutionResult']:
        """Check cancel/pause signals. Returns error result if cancelled, else None."""
        _handle = s.control_handle
        if _handle is None:
            return None

        if _handle.is_cancelled():
            return self._cancel_graph(s, "Cancellation signal received")

        return None

    async def _check_cancellation_async(self, s: 'ReactLoopState') -> Optional['ExecutionResult']:
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

    def _cancel_graph(self, s: 'ReactLoopState', reason: str) -> 'ExecutionResult':
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

    # ── Iteration limits ────────────────────────────────────────────

    def _check_iteration_limits(self, s: 'ReactLoopState') -> Optional['ExecutionResult']:
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

    # ── Recovery hint cleanup ───────────────────────────────────────

    @staticmethod
    def _clear_recovery_hints(s: 'ReactLoopState') -> None:
        """Clear stale recovery hints after a successful plan."""
        _keys = ("truncation_hint", "schema_violation_hint", "recovery_constraints")
        if any(k in s.env_context for k in _keys):
            s.env_context = dict(s.env_context)
            for k in _keys:
                s.env_context.pop(k, None)

    # ── Self-monitor ────────────────────────────────────────────────

    async def _check_self_monitor(self, s: 'ReactLoopState') -> bool:
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

    # ── Complexity routing ──────────────────────────────────────────

    async def _try_complexity_routing(self, s: 'ReactLoopState') -> Optional['ExecutionResult']:
        """Attempt complexity-based routing (batch/phased). Returns result if routed.

        Depth-aware: depth>=1 disables multi-agent and PhasedPlanner,
        only allows react internal multi-step iteration.
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

        if s.complexity.task_type == "complex":
            # Primary path: TaskExecutionPlan (structured state layer)
            if self._plan_builder is not None and self._plan_executor is not None:
                try:
                    _routing_triggered = True
                    self._record_routing_metadata(s, "task_execution_plan", True)
                    _plan = await self._plan_builder.build(
                        intent=s.intent,
                        task_def=s.task_def,
                        complexity=s.complexity,
                    )
                    _tep_env = dict(s.env_context)
                    _tep_env["_phased_original_goal"] = s.intent
                    _tep_env["_execution_depth"] = s.env_context.get("_execution_depth", 0) + 1
                    try:
                        _tep_nm = self._setup_narrative_manager(
                            s.session_id, s.exec_session_id, str(s.graph.id), s.intent, s.sub_goals,
                        )
                        async def _phase_event_cb(event_type: str, step_id: str, description: str):
                            from app.avatar.runtime.narrative.models import TranslationContext as _TC
                            await _tep_nm.on_event(event_type, step_id, _TC(semantic_label=description))
                        _tep_env["_phase_event_callback"] = _phase_event_cb
                    except Exception:
                        pass
                    logger.info(
                        "[GraphController] TaskExecutionPlan built: %d units for '%s'",
                        len(_plan.units), s.intent[:80],
                    )
                    return await self._plan_executor.execute(_plan, self, _tep_env, s.config)
                except Exception as _tep_err:
                    logger.warning(
                        "[GraphController] TaskExecutionPlan failed, falling back to PhasedPlanner: %s",
                        _tep_err,
                    )

            # Fallback: PhasedPlanner (deprecated, kept for resilience)
            if self._phased_planner is not None:
                try:
                    if self._phased_planner.should_activate(s.complexity, s.task_def, s.readiness, s.env_context):
                        _routing_triggered = True
                        self._record_routing_metadata(s, "phased_planner", True)
                        _goal_plan = await self._phased_planner.plan(s.complexity, s.intent, s.task_def)
                        _pp_env = dict(s.env_context)
                        _pp_env["_phased_original_goal"] = s.intent
                        try:
                            _pp_nm = self._setup_narrative_manager(
                                s.session_id, s.exec_session_id, str(s.graph.id), s.intent, s.sub_goals,
                            )
                            async def _phase_event_cb_pp(event_type: str, step_id: str, description: str):
                                from app.avatar.runtime.narrative.models import TranslationContext as _TC
                                await _pp_nm.on_event(event_type, step_id, _TC(semantic_label=description))
                            _pp_env["_phase_event_callback"] = _phase_event_cb_pp
                        except Exception:
                            pass
                        return await self._phased_planner.execute(_goal_plan, self, _pp_env, s.config)
                except Exception as _pp_err:
                    logger.warning(f"[GraphController] PhasedPlanner failed, falling back to ReAct: {_pp_err}")

        if not _routing_triggered:
            self._record_routing_metadata(s, "react", False)

        return None

    # ── Routing metadata ────────────────────────────────────────────

    @staticmethod
    def _record_routing_metadata(s: 'ReactLoopState', route: str, triggered: bool) -> None:
        """Record complexity routing decision in graph metadata for observability."""
        if hasattr(s.graph, 'metadata') and s.graph.metadata is not None:
            ca = s.graph.metadata.get("complexity_analysis", {})
            ca["routing_triggered"] = triggered
            ca["routed_to"] = route
            s.graph.metadata["complexity_analysis"] = ca

    # ── Fan-node execution ──────────────────────────────────────────

    async def _execute_fan_nodes(self, s: 'ReactLoopState') -> None:
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

    # ── Final result computation ────────────────────────────────────

    def _compute_final_result(self, s: 'ReactLoopState', intent: str) -> 'ExecutionResult':
        """Compute the final ExecutionResult after the loop exits normally."""
        from app.avatar.runtime.graph.models.step_node import NodeStatus

        if s.lt_ctx is not None:
            self._lt_save_snapshot(s.lt_ctx, s.graph, "final")

        completed = sum(1 for n in s.graph.nodes.values() if n.status == NodeStatus.SUCCESS)
        failed = sum(1 for n in s.graph.nodes.values() if n.status == NodeStatus.FAILED)
        skipped = sum(1 for n in s.graph.nodes.values() if n.status == NodeStatus.SKIPPED)

        # ── OutcomeReducer: unified terminal state arbiter ──────────────
        from app.avatar.runtime.verification.outcome_reducer import (
            OutcomeReducer, Outcome, GraphSignal, GateSignal,
        )
        _reducer = OutcomeReducer()
        _graph_signal = GraphSignal(
            total_nodes=len(s.graph.nodes),
            succeeded_nodes=completed,
            failed_nodes=failed,
            skipped_nodes=skipped,
        )

        # Build gate signal if verification was run
        _gate_signal = None
        if s.verification_passed:
            _gate_signal = GateSignal(verdict="pass", verifier_count=1, passed_count=1)

        # Build deliverable signal if available
        _deliverable_signal = None
        if s.deliverables:
            _unsatisfied = self._goal_tracker.get_unsatisfied_deliverables(
                s.deliverables, s.graph
            )
            _deliverable_signal = OutcomeReducer.deliverable_signal_from_specs(
                s.deliverables,
                satisfied_ids={
                    d.id for d in s.deliverables
                    if d.id not in {u.id for u in _unsatisfied}
                } if _unsatisfied is not None else set(),
            )

        _outcome = _reducer.reduce(
            graph=_graph_signal,
            deliverable=_deliverable_signal,
            gate=_gate_signal,
        )

        _outcome_to_status = {
            Outcome.COMPLETED: "success",
            Outcome.DEGRADED: "partial_success",
            Outcome.FAILED: "failed",
            Outcome.BLOCKED: "failed",
        }
        final_status = _outcome_to_status.get(_outcome, "failed")

        # DedupGuard / planner-stuck forced termination
        if s.result_status == "planner_stuck_no_output_progress":
            # Honour the lifecycle_status set by recovery_handler:
            # partial_success when prior nodes succeeded, failed otherwise.
            # Do NOT blindly override to 'failed' — that discards real work.
            _stuck_status = getattr(s, "lifecycle_status", "failed")
            if _stuck_status in ("partial_success", "failed"):
                final_status = _stuck_status
            logger.info(
                "[GraphController] Planner stuck (no output progress) → "
                f"final_status={final_status}"
            )
        elif s.result_status == "dedup_forced_finish":  # legacy compat
            logger.info(
                "[GraphController] DedupGuard forced FINISH (legacy) → overriding "
                f"final_status from '{final_status}' to 'failed'"
            )
            final_status = "failed"

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
            from app.avatar.runtime.graph.controller.synthesis.answer_synthesizer import AnswerSynthesizer
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
            error_message=s.error_message,
        )

        return result
