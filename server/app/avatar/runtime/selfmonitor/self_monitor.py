from __future__ import annotations

"""SelfMonitor — aggregates all sub-detectors for agent self-monitoring.

Aggregates StuckDetector, LoopDetector, BudgetMonitor, and
UncertaintyHeuristic.  Also performs context health checks (WorkingMemory
size) and emits all alerts via DebugEventStream.

On exception, falls back to the existing BudgetGuard.

Requirements: 9.1, 9.9, 9.10, 9.11
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ..kernel.monitor_context import MonitorContext
from ..kernel.signals import RuntimeSignal, SignalType
from ..feature_flags import record_system_fallback
from .stuck_detector import StuckDetector
from .loop_detector import LoopDetector
from .budget_monitor import BudgetMonitor
from .uncertainty_heuristic import UncertaintyHeuristic

logger = logging.getLogger(__name__)

# Context health: trigger compression when WorkingMemory exceeds this
# fraction of its size limit.
CONTEXT_HEALTH_THRESHOLD = 0.80


@dataclass
class SelfMonitorState:
    """Observable state of the SelfMonitor subsystem."""

    last_check_at: float = 0.0
    stuck_tick_count: int = 0
    loop_history: list[dict[str, Any]] = field(default_factory=list)
    budget_utilization: dict[str, float] = field(default_factory=dict)
    intervention_score: float = 0.0
    context_size_bytes: int = 0
    schema_version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_check_at": self.last_check_at,
            "stuck_tick_count": self.stuck_tick_count,
            "loop_history": list(self.loop_history),
            "budget_utilization": dict(self.budget_utilization),
            "intervention_score": self.intervention_score,
            "context_size_bytes": self.context_size_bytes,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SelfMonitorState:
        return cls(
            last_check_at=data.get("last_check_at", 0.0),
            stuck_tick_count=data.get("stuck_tick_count", 0),
            loop_history=list(data.get("loop_history") or []),
            budget_utilization=dict(data.get("budget_utilization") or {}),
            intervention_score=data.get("intervention_score", 0.0),
            context_size_bytes=data.get("context_size_bytes", 0),
            schema_version=data.get("schema_version", "1.0.0"),
        )


class SelfMonitor:
    """Aggregating monitor that runs all sub-detectors each tick.

    All alerts are emitted via DebugEventStream.  On internal exception
    the monitor falls back to the existing BudgetGuard.
    """

    def __init__(
        self,
        stuck_detector: Optional[StuckDetector] = None,
        loop_detector: Optional[LoopDetector] = None,
        budget_monitor: Optional[BudgetMonitor] = None,
        uncertainty_heuristic: Optional[UncertaintyHeuristic] = None,
        legacy_budget_guard: Optional[Any] = None,
        debug_event_stream: Optional[Any] = None,
        context_health_threshold: float = CONTEXT_HEALTH_THRESHOLD,
        compress_fn: Optional[Any] = None,
    ) -> None:
        self._stuck = stuck_detector or StuckDetector()
        self._loop = loop_detector or LoopDetector()
        self._budget = budget_monitor or BudgetMonitor()
        self._uncertainty = uncertainty_heuristic or UncertaintyHeuristic()
        self._legacy_budget_guard = legacy_budget_guard
        self._debug_stream = debug_event_stream
        self._context_health_threshold = context_health_threshold
        self._compress_fn = compress_fn
        self._state = SelfMonitorState()

    @property
    def state(self) -> SelfMonitorState:
        return self._state

    def check(self, ctx: MonitorContext) -> list[RuntimeSignal]:
        """Run all sub-detectors and return aggregated signals.

        On exception, falls back to legacy BudgetGuard.
        """
        try:
            return self._check_internal(ctx)
        except Exception as exc:
            logger.warning("[SelfMonitor] check failed, falling back: %s", exc)
            record_system_fallback(
                subsystem_name="SelfMonitor",
                error=str(exc),
                fallback_name="legacy_budget_guard",
            )
            return self._fallback_check(ctx)

    def _check_internal(self, ctx: MonitorContext) -> list[RuntimeSignal]:
        signals: list[RuntimeSignal] = []

        # 1. Stuck check
        stuck_signals = self._stuck.check(ctx)
        signals.extend(stuck_signals)

        # 2. Loop check
        loop_signals = self._loop.check(ctx)
        signals.extend(loop_signals)

        # 3. Budget check
        budget_signals = self._budget.check(ctx)
        signals.extend(budget_signals)

        # 4. Uncertainty check
        uncertainty_signals = self._uncertainty.check(ctx)
        signals.extend(uncertainty_signals)

        # 5. Context health check
        health_signals = self._check_context_health(ctx)
        signals.extend(health_signals)

        # Update state snapshot.
        self._state.last_check_at = time.time()
        self._state.context_size_bytes = ctx.working_memory_size_bytes
        self._state.budget_utilization = dict(ctx.budget_utilization)
        score = self._uncertainty.calculate_intervention_score(ctx)
        self._state.intervention_score = score

        # Emit all alerts to DebugEventStream.
        self._emit_alerts(signals, ctx)

        return signals

    def _check_context_health(self, ctx: MonitorContext) -> list[RuntimeSignal]:
        """Check WorkingMemory size and trigger compression if needed."""
        if ctx.working_memory_size_limit <= 0:
            return []

        ratio = ctx.working_memory_size_bytes / ctx.working_memory_size_limit
        if ratio <= self._context_health_threshold:
            return []

        # Trigger compression if a compress function is provided.
        if self._compress_fn is not None:
            try:
                self._compress_fn(ctx)
            except Exception as exc:
                logger.warning("[SelfMonitor] compression failed: %s", exc)

        return [
            RuntimeSignal(
                signal_type=SignalType.EMIT_STATUS_UPDATE,
                source_subsystem="SelfMonitor.context_health",
                target_task_id=ctx.task_id,
                priority=1,
                reason=(
                    f"WorkingMemory at {ratio:.0%} of limit "
                    f"({ctx.working_memory_size_bytes}/{ctx.working_memory_size_limit} bytes)"
                ),
                metadata={
                    "ratio": ratio,
                    "size_bytes": ctx.working_memory_size_bytes,
                    "limit_bytes": ctx.working_memory_size_limit,
                    "compressed": self._compress_fn is not None,
                },
            )
        ]

    def _fallback_check(self, ctx: MonitorContext) -> list[RuntimeSignal]:
        """Fallback to legacy BudgetGuard when SelfMonitor fails."""
        if self._legacy_budget_guard is None:
            return []
        try:
            result = self._legacy_budget_guard.check()
            if result is not None:
                return [
                    RuntimeSignal(
                        signal_type=SignalType.BUDGET_WARNING,
                        source_subsystem="BudgetGuard(fallback)",
                        target_task_id=ctx.task_id,
                        priority=2,
                        reason=str(result),
                    )
                ]
        except Exception:
            pass
        return []

    def _emit_alerts(self, signals: list[RuntimeSignal], ctx: MonitorContext) -> None:
        """Emit all signals to DebugEventStream (best-effort)."""
        if self._debug_stream is None:
            return

        _EVENT_TYPE_MAP = {
            SignalType.STUCK_ALERT: "monitor.stuck",
            SignalType.LOOP_ALERT: "monitor.loop",
            SignalType.BUDGET_WARNING: "monitor.budget",
            SignalType.SHRINK_BUDGET: "monitor.budget",
            SignalType.SUSPEND_TASK: "monitor.budget",
            SignalType.REQUIRE_APPROVAL: "monitor.uncertainty",
            SignalType.EMIT_STATUS_UPDATE: "monitor.context_health",
        }

        for sig in signals:
            try:
                event_type = _EVENT_TYPE_MAP.get(sig.signal_type, "monitor.alert")
                self._debug_stream.emit(
                    event_type=event_type,
                    object_type="SelfMonitor",
                    object_id=ctx.task_id,
                    payload_summary=sig.reason[:200],
                )
            except Exception:
                pass
