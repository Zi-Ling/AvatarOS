"""
FinishBiasCheck — injects goal_coverage_hint into env_context to discourage
premature FINISH when sub-goals are not yet covered.

This module is called before each planner invocation in the ReAct loop.
It enriches env_context with a structured hint that the planner can consume
to avoid generating a FINISH action when coverage is incomplete.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from app.avatar.runtime.verification.models import GoalCoverageSummary

logger = logging.getLogger(__name__)

_HINT_KEY = "goal_coverage_hint"
_FINISH_BIAS_KEY = "finish_bias_warning"


class FinishBiasCheck:
    """
    Injects coverage-based anti-FINISH hints into env_context.

    Usage:
        checker = FinishBiasCheck()
        env_context = checker.inject(env_context, coverage_summary)
    """

    def inject(
        self,
        env_context: Dict[str, Any],
        coverage_summary: Optional["GoalCoverageSummary"],
    ) -> Dict[str, Any]:
        """
        Enrich env_context with goal_coverage_hint and finish_bias_warning.

        If coverage is incomplete, adds a strong warning to discourage FINISH.
        If coverage is satisfied, clears the warning.

        Returns a new dict (does not mutate the original).
        """
        ctx = dict(env_context)

        if coverage_summary is None:
            return ctx

        hint = coverage_summary.to_planner_hint(max_chars=500)
        ctx[_HINT_KEY] = hint

        if not coverage_summary.is_currently_covered:
            unsatisfied = [
                sg.description
                for sg in coverage_summary.sub_goals
                if not sg.currently_satisfied
            ]
            warning = (
                f"[FinishBiasCheck] Coverage incomplete: "
                f"{coverage_summary.satisfied_count}/{coverage_summary.total_count} sub-goals satisfied. "
                f"Do NOT FINISH yet. Unsatisfied: {unsatisfied[:3]}"
            )
            ctx[_FINISH_BIAS_KEY] = warning
            logger.debug(f"[FinishBiasCheck] Injected anti-FINISH warning: {warning[:120]}")
        else:
            # Coverage satisfied — remove any stale warning
            ctx.pop(_FINISH_BIAS_KEY, None)

        return ctx
