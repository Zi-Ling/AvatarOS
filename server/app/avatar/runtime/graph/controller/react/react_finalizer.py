"""
ReactFinalizerMixin — finally-block logic for the ReAct loop.

Handles:
- Lifecycle status computation from final_result
- Narrative task lifecycle events (task.completed / task.failed)
- Session end callback
- Evolution pipeline finalization (sub-goal classification + on_task_finished_v2)

Extracted from graph_controller._execute_react_mode finally block.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.avatar.runtime.graph.controller.react.react_state import ReactLoopState

logger = logging.getLogger(__name__)


class ReactFinalizerMixin:
    """Mixin providing finally-block logic for GraphController."""

    async def _finalize_react_session(self, s: 'ReactLoopState') -> None:
        """
        Run all finally-block logic for a ReAct session.

        Must be called in a finally block to ensure cleanup regardless of
        how the loop exited.
        """
        from app.avatar.runtime.graph.models.step_node import NodeStatus

        # ── Emit task.completed via EventBus (unified event source) ─────
        # Must be in finally to guarantee emission regardless of exit path
        # (success, failure, cancel, iteration limit, etc.)
        if s.graph and s.graph.nodes:
            self._emit_task_completed(s.graph, s.env_context)

        # ── Compute lifecycle/result status from final_result ───────────
        if s.final_result is not None:
            fs = s.final_result.final_status
            if fs == "success":
                s.lifecycle_status = "completed"
                if s.env_context.get("verification_uncertain"):
                    s.result_status = "uncertain_success"
                else:
                    s.result_status = "success"
            elif fs == "partial_success":
                s.lifecycle_status = "completed"
                s.result_status = "partial_success"
            elif fs == "failed":
                s.lifecycle_status = "failed"
                s.result_status = "failed"

        _ns = NodeStatus

        # ── Narrative: task lifecycle events ─────────────────────────────
        try:
            from app.avatar.runtime.narrative.models import TranslationContext as _TC
            if s.result_status in ("success", "partial_success"):
                await s.narrative_manager.on_event(
                    "task.completed", step_id="__run__", context=_TC(),
                )
            elif s.result_status in ("failed", "cancelled", "uncertain_terminal"):
                await s.narrative_manager.on_event(
                    "task.failed", step_id="__run__",
                    context=_TC(
                        reason=s.error_message or "任务执行失败",
                        error_message=s.error_message,
                    ),
                )
        except Exception as _ne:
            logger.debug(f"[GraphController] Narrative task lifecycle event failed: {_ne}")

        # ── Session end ─────────────────────────────────────────────────
        await s.lifecycle.on_session_end(
            lifecycle_status=s.lifecycle_status,
            result_status=s.result_status,
            total_nodes=len(s.graph.nodes),
            completed_nodes=sum(1 for n in s.graph.nodes.values() if n.status == _ns.SUCCESS),
            failed_nodes=sum(1 for n in s.graph.nodes.values() if n.status == _ns.FAILED),
            error_message=s.error_message,
        )

        # ── Evolution pipeline finalization ─────────────────────────────
        if self._evolution_pipeline and s.evo_trace_id:
            # Guard: only enter evolution pipeline when terminal state is
            # consistent and evidence chain is trustworthy.  Otherwise only
            # record a defect_trace — don't generate noisy candidates.
            _evo_eligible = True
            _evo_skip_reason = ""

            # (a) Terminal state consistency: lifecycle_status and result_status
            #     must not contradict each other.
            _contradictions = {
                ("completed", "failed"), ("failed", "success"),
                ("failed", "partial_success"),
            }
            if (s.lifecycle_status, s.result_status) in _contradictions:
                _evo_eligible = False
                _evo_skip_reason = (
                    f"terminal state contradiction: lifecycle={s.lifecycle_status}, "
                    f"result={s.result_status}"
                )

            # (b) No nodes should exist with zero execution (all pending = stuck)
            _all_pending = all(
                n.status == _ns.PENDING for n in s.graph.nodes.values()
            ) if s.graph.nodes else False
            if _all_pending and len(s.graph.nodes) > 0:
                _evo_eligible = False
                _evo_skip_reason = "all nodes still pending — no execution evidence"

            # (c) Force-stopped sessions should not feed evolution
            if s.result_status in ("cancelled", "dedup_forced_finish"):
                _evo_eligible = False
                _evo_skip_reason = f"non-natural termination: {s.result_status}"

            # (d) Inconsistent graph health: failed nodes exist but session
            #     reports success — TerminalEvidence may have short-circuited
            #     past OutcomeReducer. Evolution candidates from such sessions
            #     are unreliable (confidence ≈ 0.00).
            if _evo_eligible and s.graph and s.graph.nodes:
                _n_failed = sum(
                    1 for n in s.graph.nodes.values() if n.status == _ns.FAILED
                )
                if _n_failed > 0 and s.result_status in ("success", "partial_success"):
                    _evo_eligible = False
                    _evo_skip_reason = (
                        f"graph health inconsistency: {_n_failed} failed node(s) "
                        f"but result_status={s.result_status}"
                    )

            if not _evo_eligible:
                logger.info(
                    "[Evolution] Skipping pipeline — recording defect_trace only: %s",
                    _evo_skip_reason,
                )
                try:
                    self._evolution_pipeline._trace_collector.mark_trace_hole(
                        trace_id=s.evo_trace_id,
                        step_id="__finalizer__",
                        reason=f"evolution_skipped: {_evo_skip_reason}",
                    )
                except Exception:
                    pass
            else:
                try:
                    from app.avatar.evolution.outcome_classifier import SubGoalResult
                    _evo_sub_goals = []

                    for sg in s.sub_goals:
                        _covered = any(
                            self._goal_tracker._node_covers(n, sg)
                            for n in s.graph.nodes.values()
                            if n.status == _ns.SUCCESS
                        )
                        _evo_sub_goals.append(SubGoalResult(
                            name=sg,
                            satisfied=_covered,
                        ))

                    _evo_decision = (
                        f"final_status={s.result_status}, "
                        f"nodes={len(s.graph.nodes)}, "
                        f"completed={sum(1 for n in s.graph.nodes.values() if n.status == _ns.SUCCESS)}, "
                        f"failed={sum(1 for n in s.graph.nodes.values() if n.status == _ns.FAILED)}"
                    )

                    await self._evolution_pipeline.on_task_finished_v2(
                        task_id=str(s.graph.id),
                        session_id=s.session_id or s.exec_session_id,
                        goal=s.intent,
                        task_type=s.env_context.get("task_type", "unknown"),
                        sub_goals=_evo_sub_goals,
                        decision_basis=_evo_decision,
                        controller_verdict=s.result_status,
                    )
                except Exception as _evo_err:
                    logger.debug(f"[GraphController] Evolution pipeline failed (non-blocking): {_evo_err}")
