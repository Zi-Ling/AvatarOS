from __future__ import annotations

"""TaskScheduler + PriorityModel — pure decision engine for multi-task scheduling.

TaskScheduler only returns RuntimeSignal suggestions; it does NOT execute tasks
or manage lifecycle.  PriorityModel computes a composite 4-dimension priority
score in [0.0, 1.0].

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ..agenda.agenda_manager import AgendaManager
from ..agenda.work_queue import WorkQueue, WorkQueueEntry
from ..kernel.signals import RuntimeSignal, SignalType
from ..kernel.task_state_machine import TaskState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PriorityModel
# ---------------------------------------------------------------------------

@dataclass
class PriorityModel:
    """Composite 4-dimension priority scorer.

    Each dimension produces a value in [0.0, 1.0].  The final score is the
    weighted sum, clamped to [0.0, 1.0].

    Requirements: 5.2, 5.4
    """

    deadline_weight: float = 0.4
    explicit_priority_weight: float = 0.3
    dependency_weight: float = 0.2
    resource_efficiency_weight: float = 0.1

    # Deadline within this many seconds triggers urgency boost
    deadline_warning_threshold_s: float = 7200.0  # 2 hours

    def calculate(self, entry: WorkQueueEntry, context: dict[str, Any]) -> float:
        """Return a priority score in [0.0, 1.0].

        ``context`` may contain:
        - ``now``            – current epoch timestamp (defaults to time.time())
        - ``completed_deps`` – set/list of completed task IDs
        - ``total_tasks``    – total number of tasks in the queue
        - ``budget_remaining_ratio`` – ratio of remaining budget (0.0-1.0)
        """
        deadline_score = self._deadline_urgency(entry, context)
        explicit_score = self._explicit_priority(entry, context)
        dep_score = self._dependency_score(entry, context)
        efficiency_score = self._resource_efficiency(entry, context)

        raw = (
            self.deadline_weight * deadline_score
            + self.explicit_priority_weight * explicit_score
            + self.dependency_weight * dep_score
            + self.resource_efficiency_weight * efficiency_score
        )
        return max(0.0, min(1.0, raw))

    # -- dimension helpers --------------------------------------------------

    def _deadline_urgency(self, entry: WorkQueueEntry, context: dict[str, Any]) -> float:
        """Urgency based on how close the deadline is.

        No deadline → 0.0 (no urgency boost).
        Within warning threshold → linearly scale from 0.5 to 1.0.
        Beyond threshold → linearly scale from 0.0 to 0.5.
        Past deadline → 1.0.
        """
        if entry.deadline is None:
            return 0.0

        now: float = context.get("now", time.time())
        remaining = entry.deadline - now

        if remaining <= 0:
            return 1.0

        threshold = self.deadline_warning_threshold_s
        if remaining <= threshold:
            # Within warning zone: 0.5 → 1.0 as remaining → 0
            return 0.5 + 0.5 * (1.0 - remaining / threshold)
        else:
            # Outside warning zone: scale 0.0 → 0.5
            # Use a 24-hour horizon as the outer bound
            outer_horizon = max(threshold * 12, remaining)
            return 0.5 * (1.0 - remaining / outer_horizon)

    @staticmethod
    def _explicit_priority(entry: WorkQueueEntry, context: dict[str, Any]) -> float:
        """Map the entry's priority_score directly (already 0.0-1.0)."""
        return max(0.0, min(1.0, entry.priority_score))

    @staticmethod
    def _dependency_score(entry: WorkQueueEntry, context: dict[str, Any]) -> float:
        """Higher score when all dependencies are satisfied.

        Fully satisfied → 1.0, partially → proportional, none declared → 1.0.
        """
        deps = entry.dependencies
        if not deps:
            return 1.0
        completed: set[str] = set(context.get("completed_deps", []))
        satisfied = sum(1 for d in deps if d in completed)
        return satisfied / len(deps)

    @staticmethod
    def _resource_efficiency(entry: WorkQueueEntry, context: dict[str, Any]) -> float:
        """Prefer tasks that fit within remaining budget.

        If budget_remaining_ratio is provided, tasks with smaller budgets
        relative to remaining resources score higher.
        """
        remaining_ratio: float = context.get("budget_remaining_ratio", 1.0)
        # Simple heuristic: remaining ratio itself is the efficiency score
        return max(0.0, min(1.0, remaining_ratio))


# ---------------------------------------------------------------------------
# TaskSchedulerState
# ---------------------------------------------------------------------------

@dataclass
class TaskSchedulerState:
    """Serializable snapshot of scheduler state."""

    current_task_id: Optional[str] = None
    last_evaluation_at: float = field(default_factory=time.time)
    switch_count: int = 0
    schema_version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_task_id": self.current_task_id,
            "last_evaluation_at": self.last_evaluation_at,
            "switch_count": self.switch_count,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskSchedulerState:
        return cls(
            current_task_id=data.get("current_task_id"),
            last_evaluation_at=data.get("last_evaluation_at", time.time()),
            switch_count=data.get("switch_count", 0),
            schema_version=data.get("schema_version", "1.0.0"),
        )


# ---------------------------------------------------------------------------
# TaskScheduler
# ---------------------------------------------------------------------------

class TaskScheduler:
    """Pure decision engine.  Returns RuntimeSignal suggestions only.

    Does NOT execute tasks or manage lifecycle.

    Requirements: 5.1, 5.3, 5.5, 5.6, 5.7, 5.8
    """

    def __init__(
        self,
        work_queue: WorkQueue,
        agenda_manager: AgendaManager,
        priority_model: Optional[PriorityModel] = None,
        switch_threshold: float = 0.2,
        deadline_warning_hours: float = 2.0,
        budget_warning_ratio: float = 0.8,
        budget_suspend_ratio: float = 1.0,
    ) -> None:
        self._work_queue = work_queue
        self._agenda = agenda_manager
        self._priority_model = priority_model or PriorityModel()
        self._switch_threshold = switch_threshold
        self._deadline_warning_hours = deadline_warning_hours
        self._budget_warning_ratio = budget_warning_ratio
        self._budget_suspend_ratio = budget_suspend_ratio
        self._state = TaskSchedulerState()

    @property
    def state(self) -> TaskSchedulerState:
        return self._state

    # ------------------------------------------------------------------
    # Main entry point — called by AgentLoop._schedule_phase()
    # ------------------------------------------------------------------

    def evaluate(self, current_task_id: Optional[str]) -> list[RuntimeSignal]:
        """Evaluate scheduling decisions and return RuntimeSignal list.

        Checks:
        1. Whether a higher-priority task should preempt the current one.
        2. Deadline warnings.
        3. Budget thresholds.
        4. Dependency constraints.
        """
        self._state.current_task_id = current_task_id
        self._state.last_evaluation_at = time.time()

        signals: list[RuntimeSignal] = []
        signals += self._check_task_switch(current_task_id)
        signals += self.check_deadlines()
        signals += self.check_budgets()
        signals += self.check_dependencies()
        return signals

    # ------------------------------------------------------------------
    # select_next — pick the best ready task from the queue
    # ------------------------------------------------------------------

    def select_next(self) -> Optional[str]:
        """Select the highest-priority task whose dependencies are met.

        Does NOT pop from the queue — only peeks.
        """
        entries = self._work_queue.list_entries()
        all_tasks = self._agenda.get_all_tasks()
        completed_ids = {
            tid for tid, st in all_tasks.items() if st == TaskState.COMPLETED
        }

        context = self._build_context(completed_ids)

        best_id: Optional[str] = None
        best_score: float = -1.0

        for entry in entries:
            # Skip tasks with incomplete dependencies
            if not self._deps_satisfied(entry, completed_ids):
                continue
            score = self._priority_model.calculate(entry, context)
            if score > best_score:
                best_score = score
                best_id = entry.task_id

        return best_id

    # ------------------------------------------------------------------
    # Sub-checks
    # ------------------------------------------------------------------

    def _check_task_switch(self, current_task_id: Optional[str]) -> list[RuntimeSignal]:
        """If a queued task's priority exceeds current by > threshold → SWITCH_TASK."""
        signals: list[RuntimeSignal] = []
        if current_task_id is None:
            return signals

        all_tasks = self._agenda.get_all_tasks()
        completed_ids = {
            tid for tid, st in all_tasks.items() if st == TaskState.COMPLETED
        }
        context = self._build_context(completed_ids)

        # Score the current task
        current_entry = self._find_entry(current_task_id)
        if current_entry is None:
            return signals
        current_score = self._priority_model.calculate(current_entry, context)

        # Check all queued entries
        for entry in self._work_queue.list_entries():
            if entry.task_id == current_task_id:
                continue
            if not self._deps_satisfied(entry, completed_ids):
                continue
            candidate_score = self._priority_model.calculate(entry, context)
            if candidate_score - current_score > self._switch_threshold:
                signals.append(
                    RuntimeSignal(
                        signal_type=SignalType.SWITCH_TASK,
                        source_subsystem="task_scheduler",
                        target_task_id=entry.task_id,
                        priority=int(candidate_score * 100),
                        reason=(
                            f"task {entry.task_id} priority {candidate_score:.2f} "
                            f"exceeds current {current_score:.2f} by "
                            f"{candidate_score - current_score:.2f} (threshold {self._switch_threshold})"
                        ),
                        metadata={
                            "candidate_score": candidate_score,
                            "current_score": current_score,
                        },
                    )
                )
                break  # Only suggest one switch per evaluation

        return signals

    def check_deadlines(self) -> list[RuntimeSignal]:
        """Emit EMIT_STATUS_UPDATE for tasks approaching their deadline."""
        signals: list[RuntimeSignal] = []
        now = time.time()
        threshold_s = self._deadline_warning_hours * 3600.0

        for entry in self._work_queue.list_entries():
            if entry.deadline is None:
                continue
            remaining = entry.deadline - now
            if 0 < remaining <= threshold_s:
                signals.append(
                    RuntimeSignal(
                        signal_type=SignalType.EMIT_STATUS_UPDATE,
                        source_subsystem="task_scheduler",
                        target_task_id=entry.task_id,
                        reason=f"deadline approaching: {remaining / 3600:.1f}h remaining",
                        metadata={"deadline": entry.deadline, "remaining_s": remaining},
                    )
                )
        return signals

    def check_budgets(self) -> list[RuntimeSignal]:
        """Check resource_budget utilization for all queued tasks.

        Each entry's resource_budget maps dimension names to limits.
        The ``utilization`` value (0.0-1.0) is expected in the budget dict
        under the key ``<dim>_utilization``.

        80% → BUDGET_WARNING, 100% → SUSPEND_TASK.
        """
        signals: list[RuntimeSignal] = []
        for entry in self._work_queue.list_entries():
            budget = entry.resource_budget
            if not budget:
                continue
            for dim, limit in budget.items():
                if dim.endswith("_utilization"):
                    continue
                util_key = f"{dim}_utilization"
                utilization = budget.get(util_key, 0.0)
                if limit <= 0:
                    continue
                ratio = utilization / limit if limit else 0.0

                if ratio >= self._budget_suspend_ratio - 1e-9:
                    signals.append(
                        RuntimeSignal(
                            signal_type=SignalType.SUSPEND_TASK,
                            source_subsystem="task_scheduler",
                            target_task_id=entry.task_id,
                            reason=f"budget exceeded: {dim} at {ratio:.0%}",
                            metadata={"dimension": dim, "ratio": ratio},
                        )
                    )
                elif ratio >= self._budget_warning_ratio - 1e-9:
                    signals.append(
                        RuntimeSignal(
                            signal_type=SignalType.BUDGET_WARNING,
                            source_subsystem="task_scheduler",
                            target_task_id=entry.task_id,
                            reason=f"budget warning: {dim} at {ratio:.0%}",
                            metadata={"dimension": dim, "ratio": ratio},
                        )
                    )
        return signals

    def check_dependencies(self) -> list[RuntimeSignal]:
        """Emit status updates for tasks blocked on incomplete dependencies."""
        signals: list[RuntimeSignal] = []
        all_tasks = self._agenda.get_all_tasks()
        completed_ids = {
            tid for tid, st in all_tasks.items() if st == TaskState.COMPLETED
        }

        for entry in self._work_queue.list_entries():
            if not entry.dependencies:
                continue
            missing = [d for d in entry.dependencies if d not in completed_ids]
            if missing:
                signals.append(
                    RuntimeSignal(
                        signal_type=SignalType.EMIT_STATUS_UPDATE,
                        source_subsystem="task_scheduler",
                        target_task_id=entry.task_id,
                        reason=f"waiting on dependencies: {missing}",
                        metadata={"missing_deps": missing},
                    )
                )
        return signals

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_entry(self, task_id: str) -> Optional[WorkQueueEntry]:
        """Find a WorkQueueEntry by task_id (linear scan, fine for V1)."""
        for entry in self._work_queue.list_entries():
            if entry.task_id == task_id:
                return entry
        return None

    @staticmethod
    def _deps_satisfied(entry: WorkQueueEntry, completed_ids: set[str]) -> bool:
        """Return True if all declared dependencies are completed."""
        if not entry.dependencies:
            return True
        return all(d in completed_ids for d in entry.dependencies)

    def _build_context(self, completed_ids: set[str]) -> dict[str, Any]:
        """Build the context dict expected by PriorityModel.calculate()."""
        return {
            "now": time.time(),
            "completed_deps": list(completed_ids),
            "budget_remaining_ratio": 1.0,
        }
