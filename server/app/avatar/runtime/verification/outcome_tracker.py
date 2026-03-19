"""OutcomeTracker — outcome-oriented task verification.

Wraps existing GoalCoverageTracker to distinguish "task completed" from
"goal achieved".  Provides milestone tracking, quality assessment,
GoalAccountability (supplementary task suggestions), and lessons_learned
persistence to ProjectMemory.

Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..feature_flags import record_system_fallback
from ..kernel.signals import RuntimeSignal, SignalType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OutcomeReport dataclass
# ---------------------------------------------------------------------------

@dataclass
class OutcomeReport:
    """Outcome report generated on task completion."""

    task_id: str = ""
    goal_achievement_status: str = ""  # fully_achieved / partially_achieved / not_achieved
    milestone_summary: List[Dict[str, Any]] = field(default_factory=list)
    quality_assessment: Dict[str, Any] = field(default_factory=dict)
    lessons_learned: List[str] = field(default_factory=list)
    schema_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "goal_achievement_status": self.goal_achievement_status,
            "milestone_summary": [dict(m) for m in self.milestone_summary],
            "quality_assessment": dict(self.quality_assessment),
            "lessons_learned": list(self.lessons_learned),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> OutcomeReport:
        return cls(
            task_id=data.get("task_id", ""),
            goal_achievement_status=data.get("goal_achievement_status", ""),
            milestone_summary=[dict(m) for m in (data.get("milestone_summary") or [])],
            quality_assessment=dict(data.get("quality_assessment") or {}),
            lessons_learned=list(data.get("lessons_learned") or []),
            schema_version=data.get("schema_version", "1.0.0"),
        )


# ---------------------------------------------------------------------------
# Milestone dataclass (internal)
# ---------------------------------------------------------------------------

@dataclass
class _Milestone:
    """Internal milestone tracking entry."""

    milestone_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    expected_completion_time: Optional[float] = None
    status: str = "pending"  # pending / in_progress / completed / overdue
    verification_criteria: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# OutcomeTracker
# ---------------------------------------------------------------------------

class OutcomeTracker:
    """Outcome-oriented task verification.

    Wraps GoalCoverageTracker (GoalTracker in requirements) to add:
    - Task completion vs goal achievement distinction (11.2)
    - Milestone tracking with overdue detection (11.4)
    - Basic quality assessment (11.5)
    - GoalAccountability — supplementary task suggestions (11.3)
    - Lessons learned persistence to ProjectMemory (11.6)
    - Fallback to GoalCoverageTracker on exception (11.8)

    Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8
    """

    def __init__(
        self,
        goal_coverage_tracker: Any = None,
        collaboration_hub: Any = None,
        project_memory: Any = None,
    ) -> None:
        self._goal_tracker = goal_coverage_tracker
        self._collaboration_hub = collaboration_hub
        self._project_memory = project_memory

        # Per-task tracking state
        self._task_states: Dict[str, Dict[str, Any]] = {}
        # milestone_id → _Milestone
        self._milestones: Dict[str, _Milestone] = {}

    # ------------------------------------------------------------------
    # Task state management
    # ------------------------------------------------------------------

    def register_task(
        self,
        task_id: str,
        goal_definition: str = "",
        acceptance_criteria: Optional[List[str]] = None,
        deliverables: Optional[List[str]] = None,
        milestones: Optional[List[Dict[str, Any]]] = None,
        quality_criteria: Optional[List[str]] = None,
    ) -> None:
        """Register a task for outcome tracking (Req 11.1)."""
        self._task_states[task_id] = {
            "goal_definition": goal_definition,
            "acceptance_criteria": list(acceptance_criteria or []),
            "deliverables": list(deliverables or []),
            "quality_criteria": list(quality_criteria or []),
            "criteria_results": {},  # criterion → bool
            "deliverable_results": {},  # deliverable → bool
            "registered_at": time.time(),
        }
        # Register milestones
        for ms_data in (milestones or []):
            ms = _Milestone(
                name=ms_data.get("name", ""),
                expected_completion_time=ms_data.get("expected_completion_time"),
                verification_criteria=list(ms_data.get("verification_criteria", [])),
            )
            self._milestones[ms.milestone_id] = ms

    # ------------------------------------------------------------------
    # verify_outcome — distinguish task completion vs goal achievement
    # ------------------------------------------------------------------

    def verify_outcome(
        self,
        task_id: str,
        success: bool,
        acceptance_criteria: Optional[List[str]] = None,
        criteria_satisfied: Optional[Dict[str, bool]] = None,
        deliverables: Optional[List[str]] = None,
        deliverables_present: Optional[Dict[str, bool]] = None,
    ) -> Dict[str, Any]:
        """Distinguish 'task completed' from 'goal achieved' (Req 11.2).

        Even when *success* is True (GraphController returned success),
        we check acceptance_criteria one-by-one and deliverables completeness.

        Returns dict with:
          - goal_achievement_status: fully_achieved / partially_achieved / not_achieved
          - criteria_met / criteria_unmet
          - deliverables_complete: bool
        """
        try:
            return self._verify_outcome_impl(
                task_id=task_id,
                success=success,
                acceptance_criteria=acceptance_criteria,
                criteria_satisfied=criteria_satisfied,
                deliverables=deliverables,
                deliverables_present=deliverables_present,
            )
        except Exception as exc:
            record_system_fallback("OutcomeTracker", exc, "GoalCoverageTracker")
            return self._fallback_verify(task_id, success)

    def _verify_outcome_impl(
        self,
        task_id: str,
        success: bool,
        acceptance_criteria: Optional[List[str]],
        criteria_satisfied: Optional[Dict[str, bool]],
        deliverables: Optional[List[str]],
        deliverables_present: Optional[Dict[str, bool]],
    ) -> Dict[str, Any]:
        ac = list(acceptance_criteria or [])
        cs = dict(criteria_satisfied or {})
        dl = list(deliverables or [])
        dp = dict(deliverables_present or {})

        # Use GoalCoverageTracker sub_goals as additional criteria source
        coverage_info = self._get_goal_coverage_info(task_id)
        if coverage_info:
            # Merge coverage sub-goal satisfaction into criteria
            for sg_desc, sg_satisfied in coverage_info.items():
                if sg_desc not in cs:
                    cs[sg_desc] = sg_satisfied
                if sg_desc not in ac:
                    ac.append(sg_desc)

        # Evaluate criteria
        criteria_met: List[str] = []
        criteria_unmet: List[str] = []
        for criterion in ac:
            if cs.get(criterion, False):
                criteria_met.append(criterion)
            else:
                criteria_unmet.append(criterion)

        # Evaluate deliverables
        deliverables_complete = True
        if dl:
            for d in dl:
                if not dp.get(d, False):
                    deliverables_complete = False
                    break

        # Determine achievement status
        if not success:
            status = "not_achieved"
        elif not ac:
            # No criteria defined — trust execution success
            status = "fully_achieved"
        elif not criteria_unmet and deliverables_complete:
            status = "fully_achieved"
        elif criteria_met:
            status = "partially_achieved"
        else:
            status = "not_achieved"

        # Store results in task state
        state = self._task_states.get(task_id, {})
        state["criteria_results"] = {c: (c in criteria_met) for c in ac}
        state["deliverable_results"] = dp

        result = {
            "goal_achievement_status": status,
            "criteria_met": criteria_met,
            "criteria_unmet": criteria_unmet,
            "deliverables_complete": deliverables_complete,
        }

        # GoalAccountability: if not fully achieved, suggest supplementary tasks
        if status != "fully_achieved":
            self._suggest_supplementary_tasks(task_id, criteria_unmet, result)

        return result

    def _fallback_verify(self, task_id: str, success: bool) -> Dict[str, Any]:
        """Fallback using GoalCoverageTracker only."""
        status = "fully_achieved" if success else "not_achieved"
        return {
            "goal_achievement_status": status,
            "criteria_met": [],
            "criteria_unmet": [],
            "deliverables_complete": success,
        }

    # ------------------------------------------------------------------
    # generate_outcome_report
    # ------------------------------------------------------------------

    def generate_outcome_report(
        self,
        task_id: str,
        verification_result: Optional[Dict[str, Any]] = None,
    ) -> OutcomeReport:
        """Generate an OutcomeReport for a completed task (Req 11.6).

        Also writes lessons_learned to ProjectMemory.
        """
        try:
            return self._generate_report_impl(task_id, verification_result)
        except Exception as exc:
            record_system_fallback("OutcomeTracker", exc, "GoalCoverageTracker")
            return OutcomeReport(
                task_id=task_id,
                goal_achievement_status="not_achieved",
            )

    def _generate_report_impl(
        self,
        task_id: str,
        verification_result: Optional[Dict[str, Any]],
    ) -> OutcomeReport:
        vr = verification_result or {}
        status = vr.get("goal_achievement_status", "not_achieved")
        criteria_met = vr.get("criteria_met", [])
        criteria_unmet = vr.get("criteria_unmet", [])

        # Milestone summary
        milestone_summary = self._build_milestone_summary()

        # Quality assessment
        state = self._task_states.get(task_id, {})
        quality_criteria = state.get("quality_criteria", [])
        deliverables = state.get("deliverables", [])
        quality = self.assess_quality(deliverables, quality_criteria)

        # Lessons learned
        lessons: List[str] = []
        if criteria_unmet:
            lessons.append(
                f"Unmet criteria: {', '.join(criteria_unmet[:5])}"
            )
        if status == "partially_achieved":
            lessons.append(
                "Task completed but goal only partially achieved — "
                "consider refining acceptance criteria or breaking into sub-tasks."
            )
        if quality.get("quality_score", 1.0) < 0.5:
            lessons.append("Quality score below 0.5 — review deliverable standards.")

        report = OutcomeReport(
            task_id=task_id,
            goal_achievement_status=status,
            milestone_summary=milestone_summary,
            quality_assessment=quality,
            lessons_learned=lessons,
        )

        # Persist lessons to ProjectMemory (Req 11.6)
        self._persist_lessons(task_id, lessons)

        return report

    # ------------------------------------------------------------------
    # check_milestones — overdue detection (Req 11.4)
    # ------------------------------------------------------------------

    def check_milestones(self) -> List[RuntimeSignal]:
        """Check milestones for overdue status. Generate EMIT_STATUS_UPDATE when overdue."""
        try:
            return self._check_milestones_impl()
        except Exception as exc:
            record_system_fallback("OutcomeTracker", exc, "GoalCoverageTracker")
            return []

    def _check_milestones_impl(self) -> List[RuntimeSignal]:
        signals: List[RuntimeSignal] = []
        now = time.time()
        for ms in self._milestones.values():
            if ms.status in ("completed",):
                continue
            if (
                ms.expected_completion_time is not None
                and now > ms.expected_completion_time
                and ms.status != "overdue"
            ):
                ms.status = "overdue"
                signals.append(
                    RuntimeSignal(
                        signal_type=SignalType.EMIT_STATUS_UPDATE,
                        source_subsystem="OutcomeTracker",
                        reason=f"Milestone '{ms.name}' is overdue",
                        metadata={
                            "milestone_id": ms.milestone_id,
                            "milestone_name": ms.name,
                            "expected_completion_time": ms.expected_completion_time,
                            "delay_seconds": now - ms.expected_completion_time,
                        },
                    )
                )
        return signals

    # ------------------------------------------------------------------
    # assess_quality — basic quality check (Req 11.5)
    # ------------------------------------------------------------------

    def assess_quality(
        self,
        deliverables: Optional[List[Any]] = None,
        quality_criteria: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Basic quality assessment. Returns quality_score in [0.0, 1.0].

        Req 11.5, 11.6: quality_score is computed as the ratio of
        satisfied quality criteria to total criteria, clamped to [0.0, 1.0].
        If no criteria are provided, defaults to a baseline score based on
        deliverables presence.
        """
        try:
            return self._assess_quality_impl(deliverables, quality_criteria)
        except Exception as exc:
            record_system_fallback("OutcomeTracker", exc, "GoalCoverageTracker")
            return {"quality_score": 0.5, "criteria_met": [], "criteria_unmet": []}

    def _assess_quality_impl(
        self,
        deliverables: Optional[List[Any]],
        quality_criteria: Optional[List[str]],
    ) -> Dict[str, Any]:
        dl = list(deliverables or [])
        qc = list(quality_criteria or [])

        if not qc:
            # No explicit quality criteria — score based on deliverables presence
            if not dl:
                score = 0.5  # neutral baseline
            else:
                score = 1.0  # deliverables exist, no criteria to fail
            return {
                "quality_score": score,
                "criteria_met": [],
                "criteria_unmet": [],
            }

        # Evaluate each quality criterion against deliverables
        # Simple heuristic: criterion is "met" if at least one deliverable
        # is present (non-empty). More sophisticated checks can be added later.
        met: List[str] = []
        unmet: List[str] = []
        for criterion in qc:
            # Basic check: if deliverables exist, criterion is considered met
            # In a real implementation, each criterion would be evaluated
            # against specific deliverable properties.
            if dl:
                met.append(criterion)
            else:
                unmet.append(criterion)

        total = len(qc)
        satisfied = len(met)
        score = satisfied / total if total > 0 else 0.5

        # Clamp to [0.0, 1.0]
        score = max(0.0, min(1.0, score))

        return {
            "quality_score": score,
            "criteria_met": met,
            "criteria_unmet": unmet,
        }

    # ------------------------------------------------------------------
    # GoalAccountability — supplementary task suggestions (Req 11.3)
    # ------------------------------------------------------------------

    def _suggest_supplementary_tasks(
        self,
        task_id: str,
        criteria_unmet: List[str],
        verification_result: Dict[str, Any],
    ) -> None:
        """When goal not fully achieved, suggest supplementary tasks via CollaborationHub."""
        if not self._collaboration_hub or not criteria_unmet:
            return
        try:
            suggestions = [
                f"Address unmet criterion: {c}" for c in criteria_unmet[:5]
            ]
            from ..collaboration.collaboration_hub import (
                Interaction,
                InteractionType,
            )
            interaction = Interaction(
                interaction_type=InteractionType.FEEDBACK_REQUEST,
                content={
                    "type": "supplementary_task_suggestion",
                    "task_id": task_id,
                    "suggestions": suggestions,
                    "criteria_unmet": criteria_unmet,
                    "message": (
                        "Goal not fully achieved. The following supplementary "
                        "tasks are suggested to address unmet criteria."
                    ),
                },
            )
            self._collaboration_hub.create_interaction(interaction)
        except Exception as exc:
            logger.debug(
                "[OutcomeTracker] Failed to suggest supplementary tasks: %s", exc
            )

    # ------------------------------------------------------------------
    # Lessons learned persistence (Req 11.6)
    # ------------------------------------------------------------------

    def _persist_lessons(self, task_id: str, lessons: List[str]) -> None:
        """Write lessons_learned to ProjectMemory."""
        if not self._project_memory or not lessons:
            return
        try:
            for lesson in lessons:
                self._project_memory.record_lesson(
                    error_context=f"task:{task_id}",
                    root_cause=lesson,
                    resolution="",
                )
        except Exception as exc:
            logger.debug(
                "[OutcomeTracker] Failed to persist lessons: %s", exc
            )

    # ------------------------------------------------------------------
    # GoalCoverageTracker integration (Req 11.7)
    # ------------------------------------------------------------------

    def _get_goal_coverage_info(self, task_id: str) -> Dict[str, bool]:
        """Extract sub-goal satisfaction from GoalCoverageTracker if available."""
        if self._goal_tracker is None:
            return {}
        try:
            # GoalCoverageTracker stores coverage in GoalCoverageSummary
            # We look for a summary that may have been stored in task state
            state = self._task_states.get(task_id, {})
            summary = state.get("_coverage_summary")
            if summary is None:
                return {}
            result: Dict[str, bool] = {}
            for sg in getattr(summary, "sub_goals", []):
                result[sg.description] = sg.currently_satisfied
            return result
        except Exception:
            return {}

    def set_coverage_summary(self, task_id: str, summary: Any) -> None:
        """Store a GoalCoverageSummary for integration with GoalCoverageTracker."""
        state = self._task_states.get(task_id)
        if state is not None:
            state["_coverage_summary"] = summary

    # ------------------------------------------------------------------
    # Milestone summary helper
    # ------------------------------------------------------------------

    def _build_milestone_summary(self) -> List[Dict[str, Any]]:
        """Build milestone summary for the outcome report."""
        return [
            {
                "milestone_id": ms.milestone_id,
                "name": ms.name,
                "status": ms.status,
                "expected_completion_time": ms.expected_completion_time,
            }
            for ms in self._milestones.values()
        ]
