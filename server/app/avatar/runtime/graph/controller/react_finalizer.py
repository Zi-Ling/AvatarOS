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
    from app.avatar.runtime.graph.controller.react_state import ReactLoopState

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
