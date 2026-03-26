"""
OutcomeReducer — the SINGLE arbiter of task terminal state.

All terminal state decisions flow through this reducer. No other component
(GraphRuntime, TerminalEvidence, VerificationGate, TaskPlanExecutor,
SessionStore) is allowed to independently decide final task status.

Input signals (facts only, no opinions):
1. graph_result: node-level success/failure counts from ExecutionGraph
2. deliverable_result: per-deliverable satisfaction from VerificationGate
3. plan_result: unit/plan aggregation from TaskExecutionPlan (if present)
4. gate_verdict: GateVerdict from CompletionGate

Output: one of completed / degraded / failed / blocked

Rules:
- completed = all blocking deliverables satisfied AND no blocking execution failure
- degraded  = deliverables satisfied BUT non-blocking execution failure exists
- failed    = blocking deliverable unsatisfied OR blocking execution failure
- blocked   = upstream dependency prevents execution
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class Outcome(str, Enum):
    COMPLETED = "completed"
    DEGRADED = "degraded"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass
class GraphSignal:
    """Facts from ExecutionGraph node execution."""
    total_nodes: int = 0
    succeeded_nodes: int = 0
    failed_nodes: int = 0
    skipped_nodes: int = 0

    @property
    def has_blocking_failure(self) -> bool:
        """A failure is blocking if ALL nodes failed (no success at all)."""
        return self.succeeded_nodes == 0 and self.failed_nodes > 0

    @property
    def has_any_failure(self) -> bool:
        return self.failed_nodes > 0

    @property
    def has_any_success(self) -> bool:
        return self.succeeded_nodes > 0


@dataclass
class DeliverableSignal:
    """Facts from deliverable verification."""
    total_deliverables: int = 0
    satisfied_deliverables: int = 0
    blocking_unsatisfied: int = 0       # required=True deliverables not satisfied

    @property
    def all_blocking_satisfied(self) -> bool:
        return self.blocking_unsatisfied == 0

    @property
    def has_deliverables(self) -> bool:
        return self.total_deliverables > 0


@dataclass
class PlanSignal:
    """Facts from TaskExecutionPlan unit aggregation."""
    total_units: int = 0
    completed_units: int = 0
    degraded_units: int = 0
    failed_units: int = 0
    blocked_units: int = 0

    @property
    def all_completed(self) -> bool:
        return self.completed_units == self.total_units and self.total_units > 0

    @property
    def has_any_completed(self) -> bool:
        return self.completed_units > 0 or self.degraded_units > 0

    @property
    def all_failed(self) -> bool:
        return (self.failed_units + self.blocked_units) == self.total_units and self.total_units > 0


@dataclass
class GateSignal:
    """Facts from CompletionGate verdict."""
    verdict: str = "uncertain"      # "pass" | "fail" | "uncertain"
    verifier_count: int = 0
    passed_count: int = 0
    failed_count: int = 0

    @property
    def is_verified_pass(self) -> bool:
        return self.verdict == "pass" and self.verifier_count > 0

    @property
    def is_unverified(self) -> bool:
        return self.verifier_count == 0


class OutcomeReducer:
    """Stateless reducer: signals in, Outcome out.

    Usage:
        reducer = OutcomeReducer()
        outcome = reducer.reduce(graph=..., deliverable=..., plan=..., gate=...)
    """

    def reduce(
        self,
        graph: Optional[GraphSignal] = None,
        deliverable: Optional[DeliverableSignal] = None,
        plan: Optional[PlanSignal] = None,
        gate: Optional[GateSignal] = None,
    ) -> Outcome:
        """Compute terminal outcome from all available signals.

        Priority order:
        1. PlanSignal (if present, it's the primary arbiter for complex tasks)
        2. DeliverableSignal (blocking deliverables override graph success)
        3. GraphSignal + GateSignal (for simple ReAct tasks)
        """
        # ── Plan-based tasks (TaskExecutionPlan path) ───────────────
        if plan is not None and plan.total_units > 0:
            return self._reduce_with_plan(plan, deliverable, gate)

        # ── Simple tasks (ReAct path) ───────────────────────────────
        return self._reduce_simple(graph, deliverable, gate)

    def _reduce_with_plan(
        self,
        plan: PlanSignal,
        deliverable: Optional[DeliverableSignal],
        gate: Optional[GateSignal],
    ) -> Outcome:
        """Reduce for TaskExecutionPlan-based tasks.

        Plan is the primary signal. Deliverable and gate are secondary.
        """
        if plan.all_failed:
            return Outcome.FAILED

        if plan.all_completed:
            # Plan says all units done — check deliverables as confirmation
            if deliverable and deliverable.has_deliverables:
                if not deliverable.all_blocking_satisfied:
                    logger.warning(
                        "[OutcomeReducer] Plan completed but %d blocking "
                        "deliverables unsatisfied → DEGRADED",
                        deliverable.blocking_unsatisfied,
                    )
                    return Outcome.DEGRADED
            return Outcome.COMPLETED

        # Partial: some completed, some failed/degraded
        if plan.has_any_completed:
            if plan.degraded_units > 0 or plan.failed_units > 0:
                return Outcome.DEGRADED
            return Outcome.COMPLETED

        return Outcome.FAILED

    def _reduce_simple(
        self,
        graph: Optional[GraphSignal],
        deliverable: Optional[DeliverableSignal],
        gate: Optional[GateSignal],
    ) -> Outcome:
        """Reduce for simple ReAct tasks (no plan)."""
        g = graph or GraphSignal()
        d = deliverable or DeliverableSignal()
        gt = gate or GateSignal()

        # No execution at all
        if g.total_nodes == 0:
            return Outcome.FAILED

        # Has blocking deliverables?
        if d.has_deliverables:
            if not d.all_blocking_satisfied:
                # Deliverables not met — even if graph succeeded
                if g.has_any_success:
                    return Outcome.DEGRADED
                return Outcome.FAILED
            # Deliverables satisfied
            if g.has_any_failure:
                return Outcome.DEGRADED
            return Outcome.COMPLETED

        # No deliverables — use graph + gate
        if g.has_blocking_failure:
            return Outcome.FAILED

        if gt.is_verified_pass:
            if g.has_any_failure:
                return Outcome.DEGRADED
            return Outcome.COMPLETED

        if gt.is_unverified:
            # 0 verifiers — don't auto-pass
            if g.has_any_success and not g.has_any_failure:
                return Outcome.COMPLETED
            if g.has_any_success and g.has_any_failure:
                return Outcome.DEGRADED
            return Outcome.FAILED

        # Gate says fail or uncertain
        if gt.verdict == "fail":
            return Outcome.FAILED

        # Uncertain gate + some success
        if g.has_any_success:
            return Outcome.DEGRADED
        return Outcome.FAILED

    # ── Convenience: build signals from existing objects ─────────────

    @staticmethod
    def graph_signal_from_result(result: Any) -> GraphSignal:
        """Build GraphSignal from an ExecutionResult."""
        return GraphSignal(
            total_nodes=getattr(result, 'completed_nodes', 0) + getattr(result, 'failed_nodes', 0) + getattr(result, 'skipped_nodes', 0),
            succeeded_nodes=getattr(result, 'completed_nodes', 0),
            failed_nodes=getattr(result, 'failed_nodes', 0),
            skipped_nodes=getattr(result, 'skipped_nodes', 0),
        )

    @staticmethod
    def plan_signal_from_plan(plan: Any) -> PlanSignal:
        """Build PlanSignal from a TaskExecutionPlan."""
        from app.avatar.runtime.task.execution_plan import UnitStatus
        units = getattr(plan, 'units', [])
        return PlanSignal(
            total_units=len(units),
            completed_units=sum(1 for u in units if u.status == UnitStatus.COMPLETED),
            degraded_units=sum(1 for u in units if u.status == UnitStatus.DEGRADED),
            failed_units=sum(1 for u in units if u.status == UnitStatus.FAILED),
            blocked_units=sum(1 for u in units if u.status == UnitStatus.BLOCKED),
        )

    @staticmethod
    def deliverable_signal_from_specs(
        deliverables: list,
        satisfied_ids: Optional[set] = None,
    ) -> DeliverableSignal:
        """Build DeliverableSignal from DeliverableSpec list."""
        satisfied_ids = satisfied_ids or set()
        blocking_unsatisfied = sum(
            1 for d in deliverables
            if getattr(d, 'required', True) and getattr(d, 'id', '') not in satisfied_ids
        )
        return DeliverableSignal(
            total_deliverables=len(deliverables),
            satisfied_deliverables=len(satisfied_ids),
            blocking_unsatisfied=blocking_unsatisfied,
        )

    @staticmethod
    def gate_signal_from_decision(decision: Any) -> GateSignal:
        """Build GateSignal from a GateDecision."""
        from app.avatar.runtime.verification.models import GateVerdict
        verdict_map = {
            GateVerdict.PASS: "pass",
            GateVerdict.FAIL: "fail",
            GateVerdict.UNCERTAIN: "uncertain",
        }
        return GateSignal(
            verdict=verdict_map.get(getattr(decision, 'verdict', None), "uncertain"),
            verifier_count=getattr(decision, 'verifier_count', 0),
            passed_count=getattr(decision, 'passed_count', 0),
            failed_count=getattr(decision, 'failed_count', 0),
        )
