from __future__ import annotations

"""BudgetGuardV2 — multi-dimension budget guard with elastic shrink.

Wraps the existing BudgetAccount and adds multi-dimension budget tracking
(token_budget, cost_budget, time_budget, api_call_budget).

- 80% utilization → BUDGET_WARNING + SHRINK_BUDGET
- 100% utilization → SUSPEND_TASK
- enter_shrink_mode(): reduce LLM call frequency, switch to economy model,
  reduce parallelism.

Requirements: 9.5, 9.6
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ..kernel.monitor_context import MonitorContext
from ..kernel.signals import RuntimeSignal, SignalType

logger = logging.getLogger(__name__)

# Budget dimension names.
DIMENSION_TOKENS = "token_budget"
DIMENSION_COST = "cost_budget"
DIMENSION_TIME = "time_budget"
DIMENSION_API_CALLS = "api_call_budget"

ALL_DIMENSIONS = [DIMENSION_TOKENS, DIMENSION_COST, DIMENSION_TIME, DIMENSION_API_CALLS]

WARNING_THRESHOLD = 0.80
SUSPEND_THRESHOLD = 1.00


@dataclass
class BudgetDimension:
    """Single budget dimension with limit and current usage."""

    name: str
    limit: float = 0.0
    used: float = 0.0

    @property
    def utilization(self) -> float:
        if self.limit <= 0:
            return 0.0
        return self.used / self.limit

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "limit": self.limit,
            "used": self.used,
            "utilization": self.utilization,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BudgetDimension:
        return cls(
            name=data.get("name", ""),
            limit=data.get("limit", 0.0),
            used=data.get("used", 0.0),
        )


class BudgetGuardV2:
    """Multi-dimension budget guard with elastic shrink mode.

    Wraps the existing BudgetAccount for actual cost tracking and adds
    multi-dimension budget monitoring with warning/suspend thresholds.
    """

    def __init__(
        self,
        budget_account: Optional[Any] = None,
        token_budget: float = 0.0,
        cost_budget: float = 0.0,
        time_budget: float = 0.0,
        api_call_budget: float = 0.0,
        warning_threshold: float = WARNING_THRESHOLD,
        suspend_threshold: float = SUSPEND_THRESHOLD,
    ) -> None:
        self._budget_account = budget_account
        self._warning_threshold = warning_threshold
        self._suspend_threshold = suspend_threshold
        self._shrink_mode = False
        self._shrink_activated_at: Optional[float] = None

        self._dimensions: dict[str, BudgetDimension] = {
            DIMENSION_TOKENS: BudgetDimension(name=DIMENSION_TOKENS, limit=token_budget),
            DIMENSION_COST: BudgetDimension(name=DIMENSION_COST, limit=cost_budget),
            DIMENSION_TIME: BudgetDimension(name=DIMENSION_TIME, limit=time_budget),
            DIMENSION_API_CALLS: BudgetDimension(name=DIMENSION_API_CALLS, limit=api_call_budget),
        }

    @property
    def shrink_mode(self) -> bool:
        return self._shrink_mode

    @property
    def dimensions(self) -> dict[str, BudgetDimension]:
        return dict(self._dimensions)

    def update_usage(self, dimension: str, used: float) -> None:
        """Update the current usage for a budget dimension."""
        if dimension in self._dimensions:
            self._dimensions[dimension].used = used

    def check(self, ctx: MonitorContext) -> list[RuntimeSignal]:
        """Evaluate budget utilization from MonitorContext and return signals.

        ``ctx.budget_utilization`` maps dimension names to utilization ratios
        (0.0–1.0+).  For dimensions with configured limits, the utilization
        is also computed from internal tracking.
        """
        # Sync from context utilization ratios.
        for dim_name, ratio in ctx.budget_utilization.items():
            if dim_name in self._dimensions and self._dimensions[dim_name].limit > 0:
                self._dimensions[dim_name].used = ratio * self._dimensions[dim_name].limit

        signals: list[RuntimeSignal] = []

        for dim in self._dimensions.values():
            if dim.limit <= 0:
                continue

            util = dim.utilization

            if util >= self._suspend_threshold:
                signals.append(
                    RuntimeSignal(
                        signal_type=SignalType.SUSPEND_TASK,
                        source_subsystem="BudgetGuardV2",
                        target_task_id=ctx.task_id,
                        priority=5,
                        reason=(
                            f"Budget dimension '{dim.name}' exhausted: "
                            f"{util:.0%} >= {self._suspend_threshold:.0%}"
                        ),
                        metadata={
                            "dimension": dim.name,
                            "utilization": util,
                            "limit": dim.limit,
                            "used": dim.used,
                        },
                    )
                )
            elif util >= self._warning_threshold:
                signals.append(
                    RuntimeSignal(
                        signal_type=SignalType.BUDGET_WARNING,
                        source_subsystem="BudgetGuardV2",
                        target_task_id=ctx.task_id,
                        priority=2,
                        reason=(
                            f"Budget dimension '{dim.name}' at {util:.0%} "
                            f"(warning threshold {self._warning_threshold:.0%})"
                        ),
                        metadata={
                            "dimension": dim.name,
                            "utilization": util,
                            "limit": dim.limit,
                            "used": dim.used,
                        },
                    )
                )
                signals.append(
                    RuntimeSignal(
                        signal_type=SignalType.SHRINK_BUDGET,
                        source_subsystem="BudgetGuardV2",
                        target_task_id=ctx.task_id,
                        priority=2,
                        reason=f"Entering shrink mode for '{dim.name}'",
                        metadata={"dimension": dim.name, "utilization": util},
                    )
                )

        return signals

    def enter_shrink_mode(self) -> None:
        """Activate shrink mode: reduce LLM call frequency, switch to
        economy model, reduce parallelism.

        The actual enforcement is done by consumers that check
        ``self.shrink_mode``.
        """
        if not self._shrink_mode:
            self._shrink_mode = True
            self._shrink_activated_at = time.time()
            logger.info("[BudgetGuardV2] Shrink mode activated")

    def exit_shrink_mode(self) -> None:
        """Deactivate shrink mode."""
        self._shrink_mode = False
        self._shrink_activated_at = None

    def get_utilization_summary(self) -> dict[str, float]:
        """Return a dict of dimension → utilization ratio."""
        return {
            name: dim.utilization
            for name, dim in self._dimensions.items()
            if dim.limit > 0
        }
