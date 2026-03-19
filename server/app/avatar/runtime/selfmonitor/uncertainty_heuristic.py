from __future__ import annotations

"""UncertaintyHeuristic — heuristic-based intervention score.

**This is a heuristic, not a calibrated probability.**

Computes an ``intervention_score`` in [0.0, 1.0] from four signals:
  1. unknown_ratio — proportion of unknown items in TaskDefinition
  2. recent_success_rate — success rate of recent steps
  3. pattern_match — whether the current step matches a known pattern
  4. consecutive_failures — number of consecutive failures

When the score exceeds a configurable threshold (default 0.7), a
REQUIRE_APPROVAL signal is emitted to request human confirmation.

Requirements: 9.7, 9.8
"""

import logging
from typing import Any

from ..kernel.monitor_context import MonitorContext
from ..kernel.signals import RuntimeSignal, SignalType

logger = logging.getLogger(__name__)

# Default weights for the four heuristic signals.
DEFAULT_WEIGHTS = {
    "unknown_ratio": 0.25,
    "failure_rate": 0.30,
    "pattern_match": 0.15,
    "consecutive_failures": 0.30,
}

DEFAULT_THRESHOLD = 0.70


class UncertaintyHeuristic:
    """Heuristic-based decision risk scoring.

    **Important**: The ``intervention_score`` is a *heuristic* indicator,
    not a calibrated probability.  It aggregates simple signals to flag
    situations where human oversight is likely beneficial.
    """

    def __init__(
        self,
        threshold: float = DEFAULT_THRESHOLD,
        weights: dict[str, float] | None = None,
        max_consecutive_failures: int = 10,
    ) -> None:
        self._threshold = threshold
        self._weights = dict(weights or DEFAULT_WEIGHTS)
        self._max_consecutive_failures = max(1, max_consecutive_failures)

    @property
    def threshold(self) -> float:
        return self._threshold

    def calculate_intervention_score(self, ctx: MonitorContext) -> float:
        """Compute the intervention score from MonitorContext signals.

        Returns a float clamped to [0.0, 1.0].
        """
        w = self._weights

        # Signal 1: unknown_ratio (already 0.0–1.0).
        s_unknown = min(max(ctx.unknown_ratio, 0.0), 1.0)

        # Signal 2: failure_rate = 1 - recent_success_rate.
        s_failure_rate = 1.0 - min(max(ctx.recent_success_rate, 0.0), 1.0)

        # Signal 3: pattern_match — inverse; no match → higher score.
        # We derive this from recent_success_rate as a proxy: low success
        # implies the current approach doesn't match known patterns.
        # A dedicated pattern DB lookup can be added later.
        s_pattern = s_failure_rate  # proxy

        # Signal 4: consecutive_failures normalised to [0.0, 1.0].
        s_consec = min(ctx.consecutive_failures / self._max_consecutive_failures, 1.0)

        raw = (
            w.get("unknown_ratio", 0.25) * s_unknown
            + w.get("failure_rate", 0.30) * s_failure_rate
            + w.get("pattern_match", 0.15) * s_pattern
            + w.get("consecutive_failures", 0.30) * s_consec
        )

        # Clamp to [0.0, 1.0].
        return min(max(raw, 0.0), 1.0)

    def check(self, ctx: MonitorContext) -> list[RuntimeSignal]:
        """Evaluate the context and return REQUIRE_APPROVAL if above threshold."""
        score = self.calculate_intervention_score(ctx)

        if score > self._threshold:
            signal = RuntimeSignal(
                signal_type=SignalType.REQUIRE_APPROVAL,
                source_subsystem="UncertaintyHeuristic",
                target_task_id=ctx.task_id,
                priority=3,
                reason=(
                    f"Intervention score {score:.2f} exceeds threshold "
                    f"{self._threshold:.2f} (heuristic, not calibrated probability)"
                ),
                metadata={
                    "intervention_score": score,
                    "threshold": self._threshold,
                    "unknown_ratio": ctx.unknown_ratio,
                    "recent_success_rate": ctx.recent_success_rate,
                    "consecutive_failures": ctx.consecutive_failures,
                },
            )
            logger.info(
                "[UncertaintyHeuristic] task=%s score=%.2f > threshold=%.2f",
                ctx.task_id,
                score,
                self._threshold,
            )
            return [signal]

        return []
