"""
CompletionGate — the single arbitration point for task completion.

Verdict rules (priority order):
  1. Any blocking verifier FAILED → FAIL
  2. No verifiers + risk_level=HIGH → UNCERTAIN
  3. No verifiers + LOW/MEDIUM + is_currently_covered → PASS
  4. All blocking verifiers PASSED + is_currently_covered → PASS
  5. Critical uncertain weight > threshold → UNCERTAIN

All VerificationResult objects are written to StepTraceStore (append-only).
Write failures set GateDecision.trace_hole=True; they never raise.
Verifier exceptions produce UNCERTAIN results and do not interrupt other verifiers.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from app.avatar.runtime.verification.models import (
    GateDecision,
    GateVerdict,
    GoalCoverageSummary,
    NormalizedGoal,
    RiskLevel,
    VerificationResult,
    VerificationStatus,
    VerificationTarget,
)
from app.avatar.runtime.verification.verifier_registry import VerifierRegistry

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.graph.storage.step_trace_store import StepTraceStore
    from app.avatar.runtime.workspace.session_workspace import SessionWorkspace

logger = logging.getLogger(__name__)


class CompletionGate:
    """
    Arbitration gate for task completion.

    Responsibilities:
    - Schedule verifiers against targets
    - Collect VerificationResult objects
    - Apply verdict rules
    - Write results to StepTraceStore (best-effort)
    """

    def __init__(
        self,
        verifier_registry: VerifierRegistry,
        trace_store: "StepTraceStore",
        llm_judge: Optional[Any] = None,
        uncertain_weight_threshold: float = 0.6,
    ) -> None:
        self._registry = verifier_registry
        self._trace_store = trace_store
        self._llm_judge = llm_judge
        self._uncertain_weight_threshold = uncertain_weight_threshold
        self._trace_hole_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        normalized_goal: NormalizedGoal,
        targets: List[VerificationTarget],
        graph: "ExecutionGraph",
        workspace: "SessionWorkspace",
        coverage_summary: GoalCoverageSummary,
        session_id: str,
        step_id: Optional[str] = None,
    ) -> GateDecision:
        """
        Run all applicable verifiers and return a GateDecision.

        Side effects:
        - All VerificationResult objects written to StepTraceStore.
        - Write failures set trace_hole=True (never raises).
        """
        verifiers = self._registry.get_verifiers(normalized_goal, targets)
        decision = GateDecision(verdict=GateVerdict.UNCERTAIN)

        # --- No verifiers case ---
        if not verifiers or not targets:
            return self._no_verifier_verdict(normalized_goal, coverage_summary)

        # --- Run verifiers ---
        all_results: List[VerificationResult] = []
        for verifier in verifiers:
            for target in targets:
                result = await self._run_one(verifier, target, workspace)
                all_results.append(result)
                self._write_trace(session_id, step_id, result, decision)

        # --- Apply verdict rules ---
        decision = self._apply_verdict(all_results, coverage_summary, normalized_goal)

        # --- LLM Judge for UNCERTAIN (Phase 3) ---
        if decision.verdict == GateVerdict.UNCERTAIN and self._llm_judge is not None:
            decision = await self._invoke_llm_judge(
                decision, normalized_goal, session_id, step_id
            )

        return decision

    # ------------------------------------------------------------------
    # Verdict logic
    # ------------------------------------------------------------------

    def _no_verifier_verdict(
        self,
        normalized_goal: NormalizedGoal,
        coverage_summary: GoalCoverageSummary,
    ) -> GateDecision:
        if normalized_goal.risk_level == RiskLevel.HIGH:
            return GateDecision(
                verdict=GateVerdict.UNCERTAIN,
                reason="No verifiers available for high-risk task",
            )
        if coverage_summary.is_currently_covered:
            return GateDecision(
                verdict=GateVerdict.PASS,
                reason="No verifiers, low/medium risk, coverage satisfied",
            )
        return GateDecision(
            verdict=GateVerdict.UNCERTAIN,
            reason="No verifiers and coverage not satisfied",
        )

    def _apply_verdict(
        self,
        results: List[VerificationResult],
        coverage_summary: GoalCoverageSummary,
        normalized_goal: NormalizedGoal,
    ) -> GateDecision:
        blocking_failed = [
            r for r in results if r.is_blocking and r.status == VerificationStatus.FAILED
        ]
        blocking_passed = [
            r for r in results if r.is_blocking and r.status == VerificationStatus.PASSED
        ]
        uncertain_results = [r for r in results if r.status == VerificationStatus.UNCERTAIN]

        passed_count = sum(1 for r in results if r.status == VerificationStatus.PASSED)
        failed_count = sum(1 for r in results if r.status == VerificationStatus.FAILED)
        uncertain_count = len(uncertain_results)

        # Rule 1: any blocking FAILED → FAIL
        if blocking_failed:
            return GateDecision(
                verdict=GateVerdict.FAIL,
                passed_count=passed_count,
                failed_count=failed_count,
                uncertain_count=uncertain_count,
                failed_results=blocking_failed,
                uncertain_results=uncertain_results,
                reason=f"{len(blocking_failed)} blocking verifier(s) failed",
            )

        # Rule 2 (verifier-first): blocking verifiers exist and ALL passed → PASS
        # Verifier 结果是确定性执行事实，优先级高于 GoalCoverageTracker 的
        # 文本匹配。当 verifier 有结论时以 verifier 为准，不再要求 coverage
        # 同时满足。GoalCoverageTracker 降级为无 verifier 场景的 fallback。
        if blocking_passed and not blocking_failed:
            return GateDecision(
                verdict=GateVerdict.PASS,
                passed_count=passed_count,
                failed_count=failed_count,
                uncertain_count=uncertain_count,
                uncertain_results=uncertain_results,
                reason="All blocking verifiers passed (verifier-first rule)",
            )

        # Rule 3: critical uncertain weight > threshold → UNCERTAIN
        critical_uncertain_weight = sum(
            v.spec.weight
            for v in self._registry._all
            for r in uncertain_results
            if r.verifier_name == v.spec.name and v.spec.severity == "critical"
        )
        total_critical_weight = sum(
            v.spec.weight for v in self._registry._all if v.spec.severity == "critical"
        )
        if (
            total_critical_weight > 0
            and critical_uncertain_weight / total_critical_weight > self._uncertain_weight_threshold
        ):
            return GateDecision(
                verdict=GateVerdict.UNCERTAIN,
                passed_count=passed_count,
                failed_count=failed_count,
                uncertain_count=uncertain_count,
                uncertain_results=uncertain_results,
                reason=f"Critical uncertain weight {critical_uncertain_weight:.2f}/{total_critical_weight:.2f} exceeds threshold",
                llm_judge_prompt=self._build_llm_prompt(results),
            )

        # Rule 4 (coverage fallback): 无 blocking verifier 时，以 coverage 为准
        if coverage_summary.is_currently_covered:
            return GateDecision(
                verdict=GateVerdict.PASS,
                passed_count=passed_count,
                failed_count=failed_count,
                uncertain_count=uncertain_count,
                uncertain_results=uncertain_results,
                reason="No blocking verifiers; coverage satisfied (fallback rule)",
            )

        # Rule 5: coverage not satisfied and no verifier evidence → FAIL
        return GateDecision(
            verdict=GateVerdict.FAIL,
            passed_count=passed_count,
            failed_count=failed_count,
            uncertain_count=uncertain_count,
            failed_results=[],
            uncertain_results=uncertain_results,
            reason="No blocking verifiers passed and sub-goals not covered",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _run_one(
        self,
        verifier: Any,
        target: VerificationTarget,
        workspace: "SessionWorkspace",
    ) -> VerificationResult:
        """Run a single verifier, catching all exceptions.
        External (SDK-registered) verifiers get extension_error event on failure.
        """
        try:
            return await verifier.verify(target, workspace)
        except Exception as exc:
            verifier_name = getattr(verifier, "spec", None) and verifier.spec.name or str(verifier)
            logger.warning(
                f"[CompletionGate] Verifier {verifier_name} raised: {exc}",
                exc_info=True,
            )
            # P3: Write extension_error event for SDK-registered verifiers
            is_external = getattr(verifier, "_is_external", False)
            if is_external and self.trace_store:
                try:
                    self.trace_store.record_event(
                        session_id="unknown",
                        step_id="",
                        event_type="extension_error",
                        payload={
                            "verifier_name": verifier_name,
                            "error": str(exc),
                            "target": str(target),
                        },
                    )
                except Exception:
                    pass
            return VerificationResult(
                verifier_name=verifier_name,
                target=target,
                status=VerificationStatus.UNCERTAIN,
                reason=f"Verifier exception: {exc}",
                is_blocking=getattr(getattr(verifier, "spec", None), "blocking", False),
            )

    def _write_trace(
        self,
        session_id: str,
        step_id: Optional[str],
        result: VerificationResult,
        decision: GateDecision,
    ) -> None:
        """Write a VerificationResult to StepTraceStore. Never raises."""
        try:
            payload = result.to_trace_payload()
            self._trace_store.record_event(
                session_id=session_id,
                event_type="verification_result",
                step_id=step_id,
                payload=payload,
            )
        except Exception as exc:
            logger.warning(f"[CompletionGate] Trace write failed: {exc}")
            decision.trace_hole = True
            self._trace_hole_count += 1

    @staticmethod
    def _build_llm_prompt(results: List[VerificationResult]) -> str:
        lines = ["Verification results for LLM judge review:"]
        for r in results:
            lines.append(
                f"  [{r.status.value}] {r.verifier_name} on {r.target.path or r.target.kind}: {r.reason}"
            )
        return "\n".join(lines)

    async def _invoke_llm_judge(
        self,
        decision: GateDecision,
        normalized_goal: NormalizedGoal,
        session_id: str,
        step_id: Optional[str],
    ) -> GateDecision:
        """
        Invoke LLM Judge for UNCERTAIN decisions.
        On success: override verdict to PASS or FAIL.
        On failure: apply risk_level fallback (HIGH → UNCERTAIN stays, LOW/MEDIUM → PASS).
        """
        try:
            prompt = decision.llm_judge_prompt or self._build_llm_prompt(
                decision.uncertain_results
            )
            verdict_str = await self._llm_judge.judge(prompt)
            if verdict_str == "pass":
                logger.info("[CompletionGate] LLM Judge: PASS")
                return GateDecision(
                    verdict=GateVerdict.PASS,
                    passed_count=decision.passed_count,
                    failed_count=decision.failed_count,
                    uncertain_count=decision.uncertain_count,
                    reason="LLM Judge: task completed",
                    trace_hole=decision.trace_hole,
                )
            else:
                logger.info("[CompletionGate] LLM Judge: FAIL")
                return GateDecision(
                    verdict=GateVerdict.FAIL,
                    passed_count=decision.passed_count,
                    failed_count=decision.failed_count,
                    uncertain_count=decision.uncertain_count,
                    reason="LLM Judge: task not completed",
                    trace_hole=decision.trace_hole,
                )
        except Exception as exc:
            logger.warning(f"[CompletionGate] LLM Judge failed: {exc}")
            # Fallback by risk level
            if normalized_goal.risk_level == RiskLevel.HIGH:
                # Keep UNCERTAIN → caller maps to uncertain_terminal
                return decision
            else:
                # LOW/MEDIUM: allow pass
                return GateDecision(
                    verdict=GateVerdict.PASS,
                    passed_count=decision.passed_count,
                    failed_count=decision.failed_count,
                    uncertain_count=decision.uncertain_count,
                    reason="LLM Judge unavailable, low/medium risk — allowing pass",
                    trace_hole=decision.trace_hole,
                )

    @property
    def trace_hole_count(self) -> int:
        return self._trace_hole_count
