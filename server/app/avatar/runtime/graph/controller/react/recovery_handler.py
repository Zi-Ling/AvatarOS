"""
RecoveryHandlerMixin — recovery path logic for the ReAct loop.

Handles:
- Truncation recovery (PlannerTruncationError → hint injection + retry)
- Schema violation replan (ActionSchemaValidator → hint + retry)
- Dedup replan (DedupGuard → hint + retry)

Each recovery path follows the same pattern:
1. Detect the condition
2. Check retry budget
3. Inject hint + recovery_constraints into env_context
4. Emit narrative recovery event
5. Return "continue" to retry, or error result to abort

Extracted from graph_controller._execute_react_mode.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.avatar.runtime.graph.controller.react.react_state import ReactLoopState

logger = logging.getLogger(__name__)


class RecoveryHandlerMixin:
    """Mixin providing recovery-path logic for GraphController."""

    async def _handle_truncation_recovery(
        self, s: 'ReactLoopState', plan_err: Exception,
    ) -> Optional[str]:
        """
        Handle PlannerTruncationError.

        Returns:
            "continue" — retry with hint injected
            "abort"    — retry budget exhausted, s.final_result set
            None       — not a truncation error, caller should re-raise
        """
        from app.avatar.planner.planners.interactive import PlannerTruncationError
        if not isinstance(plan_err, PlannerTruncationError):
            return None

        _truncation_retries = s.env_context.get("_truncation_retries", 0)
        _MAX_TRUNCATION_RETRIES = 2

        if _truncation_retries >= _MAX_TRUNCATION_RETRIES:
            logger.error(
                f"[GraphController] Truncation retry exhausted "
                f"({_truncation_retries}/{_MAX_TRUNCATION_RETRIES})"
            )
            s.error_message = (
                f"Planner output truncated {_truncation_retries + 1} times: {plan_err}"
            )
            from app.avatar.runtime.graph.models.execution_graph import GraphStatus
            s.graph.status = GraphStatus.FAILED
            s.final_result = self._make_error_result(s.graph, error_message=s.error_message)
            return "abort"

        logger.warning(
            f"[GraphController] Planner output truncated "
            f"(skill={plan_err.skill_name}), injecting hint "
            f"and retrying ({_truncation_retries + 1}/{_MAX_TRUNCATION_RETRIES})"
        )
        s.env_context = dict(s.env_context)
        s.env_context["_truncation_retries"] = _truncation_retries + 1
        s.env_context["truncation_hint"] = (
            "Your previous output was TRUNCATED by the token limit. "
            "The framework could not parse your response. To avoid this:\n"
            "1. Keep your `thought` field SHORT (1-2 sentences max).\n"
            "2. Simplify your action — do ONE thing at a time.\n"
            "3. If using python.run, write SHORTER code. Split complex "
            "operations into multiple steps.\n"
            "4. Do NOT embed large data literals in params."
        )
        s.env_context["recovery_constraints"] = {
            "force_single_action": True,
            "max_thought_words": 30,
            "max_code_lines": 20 if _truncation_retries == 0 else 10,
            "reason": "truncation",
        }
        # Narrative: recovery event
        try:
            from app.avatar.runtime.narrative.models import TranslationContext as _TC
            await s.narrative_manager.on_event(
                "recovery.truncation",
                step_id="__recovery__",
                context=_TC(retry_count=_truncation_retries + 1),
            )
        except Exception:
            pass
        return "continue"

    async def _handle_schema_replan(
        self, s: 'ReactLoopState', patch: Any,
    ) -> Optional[str]:
        """
        Validate patch against ActionSchemaValidator.

        Returns:
            "continue" — replan with hint injected
            "abort"    — replan budget exhausted, s.final_result set
            None       — no schema violations, proceed normally
        """
        try:
            from app.avatar.runtime.graph.guard.action_schema_validator import validate_patch_schemas
            _schema_violations = validate_patch_schemas(patch)
            if not _schema_violations:
                return None
        except Exception as _sv_err:
            logger.debug(f"[ActionSchemaValidator] Check skipped: {_sv_err}")
            return None

        _schema_replan_key = "_schema_replan_count"
        _schema_replans = s.env_context.get(_schema_replan_key, 0)
        _MAX_SCHEMA_REPLANS = 2

        if _schema_replans >= _MAX_SCHEMA_REPLANS:
            s.error_message = (
                f"Schema validation failed {_schema_replans + 1} times: "
                + "; ".join(v.to_hint() for v in _schema_violations)
            )
            logger.error(f"[ActionSchemaValidator] {s.error_message}")
            from app.avatar.runtime.graph.models.execution_graph import GraphStatus
            s.graph.status = GraphStatus.FAILED
            s.final_result = self._make_error_result(s.graph, error_message=s.error_message)
            return "abort"

        _hint_lines = [v.to_hint() for v in _schema_violations]
        logger.warning(
            f"[ActionSchemaValidator] Replan ({_schema_replans + 1}/{_MAX_SCHEMA_REPLANS}): "
            + "; ".join(_hint_lines)
        )
        s.env_context = dict(s.env_context)
        s.env_context[_schema_replan_key] = _schema_replans + 1
        s.env_context["schema_violation_hint"] = (
            "Your proposed action has MISSING REQUIRED PARAMETERS and was rejected.\n"
            + "\n".join(f"- {h}" for h in _hint_lines)
            + "\nPlease re-submit with ALL required parameters filled in."
        )
        s.env_context["recovery_constraints"] = {
            "force_single_action": True,
            "max_thought_words": 30,
            "reason": "schema_violation",
        }
        try:
            from app.avatar.runtime.narrative.models import TranslationContext as _TC
            await s.narrative_manager.on_event(
                "recovery.schema",
                step_id="__recovery__",
                context=_TC(retry_count=_schema_replans + 1),
            )
        except Exception:
            pass
        return "continue"

    async def _handle_dedup_replan(
        self, s: 'ReactLoopState', patch: Any,
    ) -> tuple:
        """
        Run dedup guard on patch.

        Returns:
            (patch, None)      — patch survived dedup (possibly filtered)
            (None, "continue") — all nodes deduped, hint injected, retry
            (None, "break")    — replan already used, break loop
        """
        patch = self._dedup.deduplicate_patch(patch, s.graph)
        if patch is not None:
            return patch, None

        _dedup_replan_key = "_dedup_replan_used"
        if s.env_context.get(_dedup_replan_key):
            logger.info(
                "[DedupGuard] Replan already used — all nodes "
                "still duplicates → forced FINISH (marking as failed)"
            )
            s.error_message = (
                "Task force-terminated: Planner repeatedly proposed duplicate "
                "actions after replan hint. The task may be stuck or the goal "
                "cannot be achieved with available skills."
            )
            s.lifecycle_status = "failed"
            s.result_status = "dedup_forced_finish"
            return None, "break"

        logger.info(
            "[DedupGuard] All nodes duplicates — injecting "
            "hint and giving Planner one replan chance"
        )
        s.env_context = dict(s.env_context)
        s.env_context[_dedup_replan_key] = True

        # Build structured dedup hint when TaskExecutionPlan context is available
        _required_outputs = s.env_context.get("_required_outputs")
        _skill_hint = s.env_context.get("_skill_hint")
        if _required_outputs or _skill_hint:
            hint_parts = [
                "Your last proposed step(s) are intent-equivalent to "
                "already-succeeded nodes and were filtered."
            ]
            if _required_outputs:
                pending = [o for o in _required_outputs if isinstance(o, dict)]
                if pending:
                    hint_parts.append(
                        "You still need to produce these outputs: "
                        + ", ".join(
                            f"{o.get('description', o.get('output_id', '?'))} "
                            f"({o.get('type', 'data')}"
                            f"{', .' + o['format'] if o.get('format') else ''})"
                            for o in pending
                        )
                    )
            if _skill_hint:
                prohibited = _skill_hint.get("prohibited", [])
                preferred = _skill_hint.get("preferred", [])
                if prohibited:
                    hint_parts.append(f"Do NOT use: {', '.join(prohibited)}")
                if preferred:
                    hint_parts.append(f"Try using: {', '.join(preferred)}")
            hint_parts.append(
                "If the task goal is already answered, output FINISH. "
                "Otherwise, propose a DIFFERENT step with a different skill or approach."
            )
            s.env_context["dedup_hint"] = " ".join(hint_parts)
        else:
            s.env_context["dedup_hint"] = (
                "Your last proposed step(s) are intent-equivalent to "
                "already-succeeded nodes and were filtered. "
                "If the task goal is already answered, output FINISH. "
                "Otherwise, propose a DIFFERENT step (e.g. llm.fallback "
                "to synthesize a final answer from existing results)."
            )
        try:
            from app.avatar.runtime.narrative.models import TranslationContext as _TC
            await s.narrative_manager.on_event(
                "recovery.dedup", step_id="__recovery__", context=_TC(),
            )
        except Exception:
            pass
        return None, "continue"
