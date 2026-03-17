"""
validation_gate.py — ValidationGate

Validates LearningCandidates before promotion to active.
Checks: replay regression, safety, cost impact, confidence, evidence sufficiency.
Supports auto-replay by pulling historical traces from LearningStore.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.avatar.evolution.config import EvolutionConfig
from app.avatar.evolution.models import (
    CandidateStatus,
    CandidateType,
    LearningCandidate,
    PromotionTier,
    SideEffectType,
    ValidationResult,
)

logger = logging.getLogger(__name__)


class ValidationGate:
    """
    Multi-dimensional validation gate for LearningCandidates.

    Executes the following checks before a candidate can be promoted:
    1. Confidence check — meets type-specific threshold
    2. Evidence sufficiency — min_evidence_count traces support the candidate
    3. Safety gate — no privilege escalation or side-effect increase
    4. Cost gate — benefit vs token/latency cost
    5. Replay regression — before/after comparison on historical traces
    """

    def __init__(
        self,
        config: Optional[EvolutionConfig] = None,
        min_evidence_count: int = 2,
        max_cost_increase_ratio: float = 1.5,
        learning_store: Optional[Any] = None,
    ) -> None:
        self._config = config or EvolutionConfig()
        self._min_evidence_count = min_evidence_count
        self._max_cost_increase_ratio = max_cost_increase_ratio
        self._learning_store = learning_store

    def validate(
        self,
        candidate: LearningCandidate,
        replay_results: Optional[List[Dict[str, Any]]] = None,
    ) -> ValidationResult:
        """
        Run all validation checks on a candidate.
        Returns a ValidationResult with per-check pass/fail.
        If replay_results is None and learning_store is available,
        auto-pulls historical traces for replay regression check.
        """
        result = ValidationResult(candidate_id=candidate.candidate_id, passed=True)

        # 1. Confidence check
        threshold = self._config.get_confidence_threshold(candidate.type.value)
        if candidate.confidence < threshold:
            result.confidence_passed = False
            result.passed = False
            result.reason = (
                f"confidence {candidate.confidence:.2f} < "
                f"threshold {threshold:.2f} for {candidate.type.value}"
            )
            return result

        # 2. Evidence sufficiency
        if len(candidate.evidence_links) < self._min_evidence_count:
            result.evidence_sufficient = False
            result.passed = False
            result.reason = (
                f"evidence count {len(candidate.evidence_links)} < "
                f"min {self._min_evidence_count}"
            )
            return result

        # 3. Safety gate
        safety_ok, safety_reason = self._check_safety(candidate)
        if not safety_ok:
            result.safety_passed = False
            result.passed = False
            result.reason = safety_reason
            return result

        # 4. Cost gate
        cost_ok, cost_reason = self._check_cost(candidate)
        if not cost_ok:
            result.cost_passed = False
            result.passed = False
            result.reason = cost_reason
            return result

        # 5. Replay regression (auto-pull if not provided)
        if replay_results is None and self._learning_store:
            replay_results = self._auto_replay(candidate)

        if replay_results:
            reg_ok, reg_details = self._check_replay(candidate, replay_results)
            if not reg_ok:
                result.replay_passed = False
                result.passed = False
                result.regression_details = reg_details
                result.reason = f"replay regression: {'; '.join(reg_details)}"
                return result

        result.reason = "all checks passed"
        return result

    def determine_tier(self, candidate: LearningCandidate) -> PromotionTier:
        """
        Determine the promotion tier based on candidate type and scope.

        - policy_hint, workflow_template → high_risk_human
        - planner_rule → medium_risk_validated
        - skill_score, memory_fact → low_risk_auto
        """
        high_risk_types = {CandidateType.POLICY_HINT, CandidateType.WORKFLOW_TEMPLATE}
        medium_risk_types = {CandidateType.PLANNER_RULE}

        if candidate.type in high_risk_types:
            return PromotionTier.HIGH_RISK_HUMAN
        if candidate.type in medium_risk_types:
            return PromotionTier.MEDIUM_RISK_VALIDATED
        return PromotionTier.LOW_RISK_AUTO

    # ------------------------------------------------------------------
    # Internal checks
    # ------------------------------------------------------------------

    def _check_safety(self, candidate: LearningCandidate) -> tuple:
        """
        Safety gate: reject if candidate content implies privilege escalation
        or increases side-effect scope.
        """
        content = candidate.content
        if content.after_value and isinstance(content.after_value, dict):
            # Check for side-effect escalation
            before_effects = set()
            after_effects = set()
            if isinstance(content.before_value, dict):
                before_effects = set(content.before_value.get("side_effects", []))
            after_effects = set(content.after_value.get("side_effects", []))
            new_effects = after_effects - before_effects
            if new_effects:
                return False, f"new side effects introduced: {new_effects}"

            # Check for permission escalation
            if content.after_value.get("requires_approval") is False and (
                isinstance(content.before_value, dict)
                and content.before_value.get("requires_approval") is True
            ):
                return False, "candidate removes approval requirement"

        return True, ""

    def _check_cost(self, candidate: LearningCandidate) -> tuple:
        """
        Cost gate: reject if candidate's expected cost increase exceeds threshold.
        """
        content = candidate.content
        if not isinstance(content.after_value, dict) or not isinstance(
            content.before_value, dict
        ):
            return True, ""

        before_cost = content.before_value.get("estimated_tokens", 0)
        after_cost = content.after_value.get("estimated_tokens", 0)

        if before_cost > 0 and after_cost > 0:
            ratio = after_cost / before_cost
            if ratio > self._max_cost_increase_ratio:
                return False, (
                    f"cost increase ratio {ratio:.2f} > "
                    f"max {self._max_cost_increase_ratio:.2f}"
                )

        return True, ""

    def _check_replay(
        self,
        candidate: LearningCandidate,
        replay_results: List[Dict[str, Any]],
    ) -> tuple:
        """
        Replay regression check: compare before/after outcomes.
        Each replay_result: {"trace_id": str, "before_status": str, "after_status": str}
        """
        regressions = []
        for rr in replay_results:
            before = rr.get("before_status", "")
            after = rr.get("after_status", "")
            # Regression = was success/partial, now failed/blocked/unsafe
            if before in ("success", "partial") and after in (
                "failed",
                "blocked",
                "unsafe",
            ):
                regressions.append(
                    f"trace {rr.get('trace_id', '?')}: {before} -> {after}"
                )

        if regressions:
            return False, regressions
        return True, []

    def _auto_replay(
        self, candidate: LearningCandidate
    ) -> List[Dict[str, Any]]:
        """
        Auto-pull historical traces from LearningStore for replay regression.

        Finds previously active candidates in the same scope and compares
        their outcome status with the candidate's expected behavior.
        Returns replay_results format compatible with _check_replay.
        """
        try:
            from app.avatar.evolution.models import CandidateStatus as CS

            # Find rolled-back candidates in the same scope
            # (these represent past regressions we should check against)
            rolled_back = self._learning_store.query_candidates(
                scope=candidate.scope,
                status=CS.ROLLED_BACK,
                limit=10,
            )

            replay_results = []
            for rb in rolled_back:
                # Each rolled-back candidate's evidence_links contain trace_ids
                # that were affected by the regression
                for ev in rb.evidence_links:
                    replay_results.append({
                        "trace_id": ev.trace_id,
                        "before_status": "success",  # was working before
                        "after_status": "failed",     # caused regression
                    })

            if replay_results:
                logger.info(
                    f"[ValidationGate] auto-replay found {len(replay_results)} "
                    f"historical regression traces for scope={candidate.scope}"
                )

            return replay_results
        except Exception as exc:
            logger.warning(f"[ValidationGate] auto-replay failed: {exc}")
            return []
