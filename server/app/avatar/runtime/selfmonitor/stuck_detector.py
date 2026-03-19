from __future__ import annotations

"""StuckDetector — detects when the agent is stuck with no progress.

Consecutive N ticks (default 10) with completed_items_delta == 0 and
current_blockers unchanged → STUCK_ALERT with recovery strategy suggestions.

Requirements: 9.2
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from ..kernel.monitor_context import MonitorContext
from ..kernel.signals import RuntimeSignal, SignalType

logger = logging.getLogger(__name__)

# Recovery strategies suggested when stuck is detected.
RECOVERY_STRATEGIES = [
    "request_human_help",
    "switch_approach",
    "suspend_and_switch",
]


@dataclass
class _StuckState:
    """Internal tracking state for stuck detection."""

    consecutive_no_progress_ticks: int = 0
    last_blockers: list[str] | None = None  # None = first check (no baseline yet)


class StuckDetector:
    """Detects when the agent makes no progress for consecutive ticks.

    When *completed_items_delta == 0* **and** *current_blockers* remain
    unchanged for ``threshold`` consecutive ticks, a ``STUCK_ALERT``
    signal is emitted with suggested recovery strategies.
    """

    def __init__(self, threshold: int = 10) -> None:
        self._threshold = max(1, threshold)
        # Per-task tracking
        self._states: dict[str, _StuckState] = {}

    @property
    def threshold(self) -> int:
        return self._threshold

    def check(self, ctx: MonitorContext) -> list[RuntimeSignal]:
        """Evaluate the monitor context and return signals if stuck."""
        state = self._states.setdefault(ctx.task_id, _StuckState())

        has_progress = ctx.completed_items_delta > 0
        # First check for this task: establish baseline, don't treat as change
        if state.last_blockers is None:
            blockers_changed = False
        else:
            blockers_changed = sorted(ctx.current_blockers) != sorted(state.last_blockers)

        if has_progress or blockers_changed:
            # Reset counter — there is progress or the situation changed.
            state.consecutive_no_progress_ticks = 0
            state.last_blockers = list(ctx.current_blockers)
            return []

        # No progress and blockers unchanged.
        state.consecutive_no_progress_ticks += 1
        state.last_blockers = list(ctx.current_blockers)

        if state.consecutive_no_progress_ticks >= self._threshold:
            signal = RuntimeSignal(
                signal_type=SignalType.STUCK_ALERT,
                source_subsystem="StuckDetector",
                target_task_id=ctx.task_id,
                priority=3,
                reason=(
                    f"No progress for {state.consecutive_no_progress_ticks} "
                    f"consecutive ticks (threshold={self._threshold})"
                ),
                metadata={
                    "consecutive_ticks": state.consecutive_no_progress_ticks,
                    "threshold": self._threshold,
                    "current_blockers": list(ctx.current_blockers),
                    "recovery_strategies": list(RECOVERY_STRATEGIES),
                },
            )
            logger.warning(
                "[StuckDetector] task=%s stuck for %d ticks",
                ctx.task_id,
                state.consecutive_no_progress_ticks,
            )
            return [signal]

        return []

    def reset(self, task_id: str) -> None:
        """Reset tracking state for a task."""
        self._states.pop(task_id, None)
