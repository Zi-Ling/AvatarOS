# app/services/computer/stuck_detector.py
"""StuckDetector — 卡住检测与 replan 触发."""

from __future__ import annotations

from .models import (
    ComputerUseSessionState,
    StuckCheckResult,
    StuckType,
    TransitionType,
    TransitionVerdict,
)


class StuckDetector:
    """卡住检测器."""

    def __init__(
        self,
        max_unchanged_streak: int = 3,
        max_failed_streak: int = 3,
        max_unexpected_streak: int = 2,
    ) -> None:
        self._max_unchanged = max_unchanged_streak
        self._max_failed = max_failed_streak
        self._max_unexpected = max_unexpected_streak

    def check(self, session_state: ComputerUseSessionState) -> StuckCheckResult:
        """检查是否卡住."""
        if session_state.unchanged_streak >= self._max_unchanged:
            rec = "user_intervention" if session_state.replan_count > 0 else "replan"
            return StuckCheckResult(
                is_stuck=True,
                stuck_type=StuckType.STATE_UNCHANGED,
                recommendation=rec,
            )
        if session_state.failure_streak >= self._max_failed:
            rec = "user_intervention" if session_state.replan_count > 0 else "replan"
            return StuckCheckResult(
                is_stuck=True,
                stuck_type=StuckType.ACTION_FAILED,
                recommendation=rec,
            )
        if session_state.unexpected_streak >= self._max_unexpected:
            return StuckCheckResult(
                is_stuck=True,
                stuck_type=StuckType.UNEXPECTED_TRANSITION,
                recommendation="replan",
            )
        return StuckCheckResult(is_stuck=False)

    def record_verdict(
        self,
        session_state: ComputerUseSessionState,
        verdict: TransitionVerdict,
    ) -> None:
        """记录本轮判定结果，更新连续计数."""
        vt = verdict.verdict_type

        if vt == TransitionType.NO_CHANGE:
            session_state.unchanged_streak += 1
            session_state.failure_streak = 0
            session_state.unexpected_streak = 0
        elif vt == TransitionType.UNEXPECTED_TRANSITION:
            session_state.unexpected_streak += 1
            session_state.unchanged_streak = 0
            session_state.failure_streak = 0
        elif vt == TransitionType.SUCCESS_TRANSITION:
            self.reset_streak(session_state)
        else:
            # UNKNOWN — treat as potential failure
            session_state.failure_streak += 1
            session_state.unchanged_streak = 0
            session_state.unexpected_streak = 0

    def reset_streak(self, session_state: ComputerUseSessionState) -> None:
        """成功后重置连续计数."""
        session_state.failure_streak = 0
        session_state.unchanged_streak = 0
        session_state.unexpected_streak = 0
