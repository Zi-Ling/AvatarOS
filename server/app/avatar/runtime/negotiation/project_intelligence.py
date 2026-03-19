"""ProjectIntelligence — milestone management, risk alerts, confirmation push.

Requirements: 6.4, 6.5, 6.6, 6.7
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from ..kernel.signals import RuntimeSignal, SignalType

logger = logging.getLogger(__name__)

# Risk thresholds
_CONSECUTIVE_FAILURE_THRESHOLD = 3
_RESOURCE_OVERBUDGET_RATIO = 1.5
_PROGRESS_DEADLINE_RATIO = 0.5
# Confirmation push timeout (seconds)
_CONFIRMATION_TIMEOUT_S = 15 * 60  # 15 minutes


class ProjectIntelligence:
    """Milestone management + risk alerts + confirmation push.

    Requirements: 6.4, 6.5, 6.6, 6.7
    """

    def __init__(self) -> None:
        self._milestones: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Milestone auto-organization
    # ------------------------------------------------------------------

    def organize_milestones(self, goal_plan: Any) -> List[Dict[str, Any]]:
        """Generate milestone definitions for each PhasePlan in a GoalPlan.

        Requirements: 6.4
        """
        phases = getattr(goal_plan, "phases", []) or []
        milestones: List[Dict[str, Any]] = []
        for phase in phases:
            phase_id = getattr(phase, "phase_id", str(uuid.uuid4()))
            milestone = {
                "milestone_id": f"ms_{phase_id}",
                "milestone_name": getattr(phase, "phase_objective", f"Phase {phase_id}"),
                "expected_completion_time": None,  # V1: not estimated
                "verification_criteria": getattr(phase, "phase_acceptance_criteria", []),
                "status": getattr(phase, "status", "pending"),
            }
            milestones.append(milestone)
            self._milestones[milestone["milestone_id"]] = milestone
        return milestones

    # ------------------------------------------------------------------
    # Milestone overdue check
    # ------------------------------------------------------------------

    def check_milestone_overdue(self) -> List[RuntimeSignal]:
        """Check if any milestones are overdue.

        Returns RuntimeSignal list for overdue milestones.
        """
        signals: List[RuntimeSignal] = []
        now = time.time()
        for ms_id, ms in self._milestones.items():
            expected = ms.get("expected_completion_time")
            status = ms.get("status", "pending")
            if expected is not None and now > expected and status in ("pending", "in_progress"):
                signals.append(
                    RuntimeSignal(
                        signal_type=SignalType.EMIT_STATUS_UPDATE,
                        source_subsystem="project_intelligence",
                        reason=f"Milestone '{ms.get('milestone_name', ms_id)}' is overdue",
                        metadata={"milestone_id": ms_id},
                    )
                )
        return signals

    # ------------------------------------------------------------------
    # Risk signal detection
    # ------------------------------------------------------------------

    def detect_risk_signals(self, task_state: Any) -> List[RuntimeSignal]:
        """Detect risk signals from task execution state.

        Triggers:
        - 3 consecutive failures
        - Resource > 150% budget
        - Deadline approaching with < 50% progress

        Requirements: 6.5
        """
        signals: List[RuntimeSignal] = []

        # Consecutive failures
        consecutive_failures = getattr(task_state, "consecutive_failures", 0)
        if consecutive_failures >= _CONSECUTIVE_FAILURE_THRESHOLD:
            signals.append(
                RuntimeSignal(
                    signal_type=SignalType.EMIT_STATUS_UPDATE,
                    source_subsystem="project_intelligence",
                    priority=2,
                    reason=f"Risk: {consecutive_failures} consecutive failures detected",
                    metadata={"risk_type": "consecutive_failures", "count": consecutive_failures},
                )
            )

        # Resource overbudget
        budget_utilization = getattr(task_state, "budget_utilization", {})
        if isinstance(budget_utilization, dict):
            for dimension, ratio in budget_utilization.items():
                if isinstance(ratio, (int, float)) and ratio > _RESOURCE_OVERBUDGET_RATIO:
                    signals.append(
                        RuntimeSignal(
                            signal_type=SignalType.BUDGET_WARNING,
                            source_subsystem="project_intelligence",
                            priority=2,
                            reason=f"Risk: resource '{dimension}' at {ratio:.0%} of budget (>{_RESOURCE_OVERBUDGET_RATIO:.0%})",
                            metadata={"risk_type": "resource_overbudget", "dimension": dimension, "ratio": ratio},
                        )
                    )

        # Deadline approaching with low progress
        deadline = getattr(task_state, "deadline", None)
        progress = getattr(task_state, "progress_ratio", None)
        if deadline is not None and progress is not None:
            now = time.time()
            if now < deadline and progress < _PROGRESS_DEADLINE_RATIO:
                remaining_ratio = (deadline - now) / max(deadline - getattr(task_state, "started_at", now), 1)
                if remaining_ratio < 0.3:
                    signals.append(
                        RuntimeSignal(
                            signal_type=SignalType.EMIT_STATUS_UPDATE,
                            source_subsystem="project_intelligence",
                            priority=2,
                            reason=f"Risk: deadline approaching with only {progress:.0%} progress",
                            metadata={"risk_type": "deadline_risk", "progress": progress},
                        )
                    )

        return signals

    # ------------------------------------------------------------------
    # Pending confirmation push
    # ------------------------------------------------------------------

    def check_pending_confirmations(
        self,
        collaboration_hub: Any,
    ) -> List[RuntimeSignal]:
        """Check for interactions pending > 15 min without response.

        Generates follow_up_reminder signals.
        Requirements: 6.6
        """
        signals: List[RuntimeSignal] = []
        if collaboration_hub is None:
            return signals

        try:
            pending = collaboration_hub.list_pending()
        except Exception:
            return signals

        now = time.time()
        for interaction in pending:
            created_at = getattr(interaction, "created_at", 0)
            if now - created_at > _CONFIRMATION_TIMEOUT_S:
                signals.append(
                    RuntimeSignal(
                        signal_type=SignalType.EMIT_STATUS_UPDATE,
                        source_subsystem="project_intelligence",
                        reason=f"Follow-up reminder: interaction {getattr(interaction, 'interaction_id', '?')} pending > 15 min",
                        metadata={
                            "action": "follow_up_reminder",
                            "interaction_id": getattr(interaction, "interaction_id", ""),
                        },
                    )
                )
        return signals
