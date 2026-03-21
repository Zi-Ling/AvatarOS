"""
ReactFinishHandlerMixin — FINISH decision logic for the ReAct loop.

Handles:
- Sub-goal coverage check (reject FINISH if uncovered)
- Deliverable coverage check
- DeliveryGate (long-task)
- VerificationGate + narrative events
- Gate result → return value mapping

Extracted from graph_controller._execute_react_mode.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.avatar.runtime.graph.controller.react_state import ReactLoopState

logger = logging.getLogger(__name__)


class ReactFinishHandlerMixin:
    """Mixin providing FINISH-decision logic for GraphController."""

    async def _handle_finish_decision(self, s: 'ReactLoopState') -> str:
        """
        Process a FINISH signal from the planner.

        Returns one of:
            "continue"       — FINISH rejected, loop should continue
            "break_pass"     — verified success, break loop
            "break_partial"  — partial success, return immediately
            "break_failed"   — verification failed, return immediately
            "break_uncertain"— uncertain, return immediately
            "break"          — normal break (all goals covered, no gate)
        """
        from app.avatar.runtime.graph.models.step_node import NodeStatus

        logger.info("Planner returned FINISH")

        # ── Consecutive FINISH rejection cap ───────────────────────────
        # If Planner keeps returning FINISH despite rejection hints,
        # force-accept after MAX_CONSECUTIVE_FINISH_REJECTIONS to avoid
        # burning the entire budget on a loop the Planner can't resolve.
        _at_rejection_cap = (
            s.consecutive_finish_rejections >= s.MAX_CONSECUTIVE_FINISH_REJECTIONS
        )
        if _at_rejection_cap:
            logger.warning(
                f"[GoalTracker] FINISH force-accepted after "
                f"{s.consecutive_finish_rejections} consecutive rejections — "
                f"Planner cannot resolve remaining gaps"
            )
            # Clear stale hints so they don't pollute the final result
            s.env_context = dict(s.env_context)
            s.env_context.pop("uncovered_sub_goals", None)
            s.env_context.pop("unsatisfied_deliverables", None)
            s.env_context.pop("goal_tracker_hint", None)
            # Fall through to verification gate (skip sub-goal/deliverable checks)
        else:
            # ── Sub-goal coverage ───────────────────────────────────────
            uncovered = self._goal_tracker.get_uncovered_sub_goals(
                s.sub_goals, s.graph
            )
            if uncovered:
                s.consecutive_finish_rejections += 1
                logger.warning(
                    f"[GoalTracker] FINISH rejected ({s.consecutive_finish_rejections}/"
                    f"{s.MAX_CONSECUTIVE_FINISH_REJECTIONS}): "
                    f"{len(uncovered)} uncovered: {uncovered}"
                )
                s.env_context = dict(s.env_context)
                s.env_context["uncovered_sub_goals"] = uncovered
                s.env_context["goal_tracker_hint"] = (
                    f"The following sub-goals are NOT yet completed: {uncovered}. "
                    f"You MUST complete them before finishing."
                )
                return "continue"

            # ── Deliverable coverage ────────────────────────────────────
            if s.deliverables:
                _unsatisfied = self._goal_tracker.get_unsatisfied_deliverables(
                    s.deliverables, s.graph
                )
                if _unsatisfied:
                    s.consecutive_finish_rejections += 1
                    _missing_fmts = [f"{d.id}:{d.format}" for d in _unsatisfied]
                    logger.warning(
                        f"[GoalTracker] FINISH rejected ({s.consecutive_finish_rejections}/"
                        f"{s.MAX_CONSECUTIVE_FINISH_REJECTIONS}): "
                        f"{len(_unsatisfied)} unsatisfied deliverables: {_missing_fmts}"
                    )
                    s.env_context = dict(s.env_context)
                    s.env_context["unsatisfied_deliverables"] = _missing_fmts
                    s.env_context["goal_tracker_hint"] = (
                        f"The following deliverables have NOT been produced yet: "
                        f"{_missing_fmts}. You MUST produce ALL requested file "
                        f"formats before finishing."
                    )
                    return "continue"

        # Reset rejection counter — FINISH passed sub-goal + deliverable checks
        s.consecutive_finish_rejections = 0

        # ── Long-task: DeliveryGate ─────────────────────────────────────
        if s.lt_ctx is not None:
            _dg_result = await self._lt_run_delivery_gate(s.lt_ctx)
            if _dg_result and not _dg_result.get("passed", True):
                logger.warning(
                    f"[DeliveryGate] Not passed: {_dg_result.get('reasons')}"
                )
                s.env_context = dict(s.env_context)
                s.env_context["delivery_gate_reasons"] = _dg_result.get("reasons", [])
                s.env_context["goal_tracker_hint"] = (
                    f"Delivery gate check failed: {_dg_result.get('reasons')}. "
                    f"Please address these issues before finishing."
                )
                return "continue"

        # ── Verification gate ───────────────────────────────────────────
        from app.avatar.runtime.narrative.models import TranslationContext as _TC
        try:
            await s.narrative_manager.on_event(
                "verification.start", step_id="__run__", context=_TC(),
            )
        except Exception as _ne:
            logger.debug(f"[GraphController] Narrative verification.start failed: {_ne}")

        _gate_result = await self._run_verification_gate(
            intent=s.intent, graph=s.graph, workspace=s.workspace,
            env_context=s.env_context,
            session_id=s.session_id or s.exec_session_id,
            task_context=None,
        )

        # ── Narrative for gate result ───────────────────────────────────
        try:
            if _gate_result == "break_pass":
                await s.narrative_manager.on_event(
                    "verification.pass", step_id="__run__", context=_TC(),
                )
            elif _gate_result == "break_partial":
                await s.narrative_manager.on_event(
                    "verification.fail", step_id="__run__",
                    context=_TC(reason="部分完成"),
                )
            elif _gate_result in ("break_failed", "break_uncertain"):
                await s.narrative_manager.on_event(
                    "verification.fail", step_id="__run__",
                    context=_TC(reason="验证失败"),
                )
            elif _gate_result == "continue":
                await s.narrative_manager.on_event(
                    "verification.fail", step_id="__run__",
                    context=_TC(reason="验证未通过，准备重试"),
                )
                _hint = (s.env_context.get("verification_failed_hints") or ["正在重新分析失败原因"])[0]
                await s.narrative_manager.on_event(
                    "retry.triggered", step_id="__run__",
                    context=_TC(reason=_hint, retry_count=1),
                )
        except Exception as _ne:
            logger.debug(f"[GraphController] Narrative verification event failed: {_ne}")

        # ── Map gate result to loop action ──────────────────────────────
        if _gate_result == "continue":
            s.env_context = dict(s.env_context)
            return "continue"
        elif _gate_result == "break_partial":
            s.lifecycle_status = "completed"
            s.result_status = "partial_success"
            from app.avatar.runtime.graph.runtime.graph_runtime import ExecutionResult
            s.final_result = ExecutionResult(
                success=False, final_status="partial_success",
                completed_nodes=sum(1 for n in s.graph.nodes.values() if n.status == NodeStatus.SUCCESS),
                failed_nodes=sum(1 for n in s.graph.nodes.values() if n.status == NodeStatus.FAILED),
                skipped_nodes=sum(1 for n in s.graph.nodes.values() if n.status == NodeStatus.SKIPPED),
                graph=s.graph,
            )
            return "break_partial"
        elif _gate_result == "break_failed":
            s.lifecycle_status = "failed"
            s.result_status = "failed"
            s.final_result = self._make_error_result(
                s.graph, "Verification failed: repair exhausted"
            )
            return "break_failed"
        elif _gate_result == "break_uncertain":
            s.lifecycle_status = "failed"
            s.result_status = "uncertain_terminal"
            s.final_result = self._make_error_result(
                s.graph, "Verification uncertain: high-risk task requires human review"
            )
            return "break_uncertain"

        if _gate_result == "break_pass":
            s.verification_passed = True

        logger.info("Planner returned FINISH -- all sub-goals covered")
        return "break"
