"""
Verification gate mixin for GraphController.

Runs CompletionGate at FINISH decision points to verify goal achievement,
trigger repair loops, and handle uncertain verdicts.

Extracted from graph_controller.py to keep the controller focused on
orchestration logic.
"""

from __future__ import annotations
from typing import Dict, Any, Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph

logger = logging.getLogger(__name__)


class VerificationGateMixin:
    """Mixin providing verification gate methods for GraphController."""

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
            from app.avatar.runtime.graph.storage.step_trace_store import get_step_trace_store
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

            # Canonicalize all target paths: container → host
            from app.avatar.runtime.workspace.path_canonical import canonicalize_path
            _host_ws = env_context.get("workspace_path")
            _session_ws = env_context.get("session_workspace_path")
            for t in targets:
                if t.path:
                    t.path = canonicalize_path(t.path, _host_ws, _session_ws)

            env_context["verification_targets"] = targets

            _tracker = GoalCoverageTracker(_normalizer)
            if "goal_coverage_summary" not in env_context:
                env_context["goal_coverage_summary"] = _tracker.initialize(normalized_goal)
            coverage_summary = _tracker.update_after_round(
                env_context["goal_coverage_summary"], graph, workspace,
                env_context=env_context,
            )
            env_context["goal_coverage_summary"] = coverage_summary
            env_context["goal_coverage_hint"] = coverage_summary.to_planner_hint()

            _trace_store = get_step_trace_store()
            _registry = VerifierRegistry()
            _gate = CompletionGate(_registry, _trace_store)

            # Collect output_contracts from succeeded graph nodes for
            # VerifierRegistry auto-selection based on ValueKind
            _output_contracts = {}
            try:
                from app.avatar.runtime.graph.models.step_node import NodeStatus as _NS
                for _n in graph.nodes.values():
                    if _n.status == _NS.SUCCESS:
                        _oc = (_n.metadata or {}).get("output_contract")
                        if _oc is not None:
                            _output_contracts[_n.id] = _oc
            except Exception:
                pass

            decision = await _gate.evaluate(
                normalized_goal=normalized_goal,
                targets=targets,
                graph=graph,
                workspace=workspace,
                coverage_summary=coverage_summary,
                session_id=session_id,
                context={
                    "graph": graph,
                    "output_contracts": _output_contracts,
                    "goal_type": normalized_goal.goal_type,
                },
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
                env_context["verification_uncertain"] = True
                return "break_pass"

        except Exception as exc:
            logger.warning(f"[VerificationGate] Error, allowing FINISH: {exc}", exc_info=True)
        return "break_pass"
