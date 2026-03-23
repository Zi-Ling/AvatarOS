# app/services/computer/state_judge.py
"""StateTransitionJudge — 状态转移判定器."""

from __future__ import annotations

from .models import (
    GUIState,
    TransitionType,
    TransitionVerdict,
    VerificationResult,
    VerificationVerdict,
)


class StateTransitionJudge:
    """状态转移判定器."""

    def judge(
        self,
        before: GUIState,
        after: GUIState,
        expected_transition: str,
        verification_result: VerificationResult,
    ) -> TransitionVerdict:
        """综合 GUIState 差异和 VerificationEngine 结果，判定转移类型."""
        hash_changed = before.state_hash != after.state_hash
        verdict = verification_result.verdict

        if verdict == VerificationVerdict.PASS:
            return TransitionVerdict(
                verdict_type=TransitionType.SUCCESS_TRANSITION,
                confidence=0.9 if hash_changed else 0.7,
                reason="Verification passed" + (" + state hash changed" if hash_changed else ""),
            )

        if verdict == VerificationVerdict.FAIL:
            if not hash_changed:
                return TransitionVerdict(
                    verdict_type=TransitionType.NO_CHANGE,
                    confidence=0.9,
                    reason="Verification failed and state hash unchanged",
                )
            return TransitionVerdict(
                verdict_type=TransitionType.UNEXPECTED_TRANSITION,
                confidence=0.8,
                reason="Verification failed but state hash changed — unexpected direction",
            )

        # INCONCLUSIVE
        if hash_changed:
            return TransitionVerdict(
                verdict_type=TransitionType.UNKNOWN,
                confidence=0.4,
                reason="Verification inconclusive, state hash changed",
            )
        return TransitionVerdict(
            verdict_type=TransitionType.UNKNOWN,
            confidence=0.3,
            reason="Verification inconclusive, state hash unchanged",
        )
