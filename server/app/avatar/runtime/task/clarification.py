"""
Clarification data models for execution readiness assessment.

ClarificationEngine (assess logic) will be added in Task 9.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List

from .task_definition import Assumption


class QuestionPriority(str, Enum):
    """Blocking question priority — higher priority = asked first."""
    AFFECTS_OBJECTIVE = "affects_objective"        # highest
    AFFECTS_DELIVERABLE = "affects_deliverable"
    AFFECTS_HIGH_RISK = "affects_high_risk"
    OTHER_BLOCKING = "other_blocking"              # lowest


@dataclass
class BlockingQuestion:
    """A question that blocks execution until answered."""
    question: str
    priority: QuestionPriority
    related_field: str = ""  # field path in TaskDefinition


@dataclass
class ExecutionReadiness:
    """Result of ClarificationEngine.assess() — execution readiness status."""
    status: str = "ready"  # "ready" / "blocked" / "conditional"
    blocking_questions: List[BlockingQuestion] = field(default_factory=list)
    suggested_assumptions: List[Assumption] = field(default_factory=list)
    ambiguity_level: str = "low"  # "low" / "medium" / "high"
    schema_version: str = "1.0.0"


import logging
import signal
import threading
from typing import List

from .task_definition import Assumption, FieldSource, TaskDefinition

logger = logging.getLogger(__name__)

# Priority ordering (lower index = higher priority)
_PRIORITY_ORDER = [
    QuestionPriority.AFFECTS_OBJECTIVE,
    QuestionPriority.AFFECTS_DELIVERABLE,
    QuestionPriority.AFFECTS_HIGH_RISK,
    QuestionPriority.OTHER_BLOCKING,
]

# Maximum blocking questions in first round
_MAX_FIRST_ROUND = 3

# Performance guard: assessment timeout in seconds
_ASSESS_TIMEOUT_SECONDS = 5.0


class ClarificationEngine:
    """Execution readiness assessor.

    Evaluates a TaskDefinition to determine if execution can proceed,
    needs clarification, or can proceed with assumptions.
    """

    def assess(self, task_def: TaskDefinition) -> ExecutionReadiness:
        """Assess execution readiness from a TaskDefinition.

        Performance guard: if assessment exceeds 5 seconds, degrade to
        conditional (with suggested_assumptions) or ready (without).

        Steps:
        1. Compute ambiguity_level
        2. Classify open_questions → blocking / non_blocking
        3. Sort by priority, cap at 3
        4. Determine status
        5. Convert non_blocking to suggested_assumptions
        """
        result_holder: List[ExecutionReadiness] = []
        error_holder: List[Exception] = []

        def _do_assess() -> None:
            try:
                result_holder.append(self._assess_impl(task_def))
            except Exception as e:
                error_holder.append(e)

        thread = threading.Thread(target=_do_assess, daemon=True)
        thread.start()
        thread.join(timeout=_ASSESS_TIMEOUT_SECONDS)

        if result_holder:
            return result_holder[0]

        # Timeout or error → degrade
        logger.warning(
            "[ClarificationEngine] Assessment timed out or failed, degrading"
        )
        # Build degraded result
        assumptions = self._to_assumptions(task_def.open_questions) if task_def.open_questions else []
        if assumptions:
            return ExecutionReadiness(
                status="conditional",
                suggested_assumptions=assumptions,
                ambiguity_level="medium",
            )
        return ExecutionReadiness(status="ready", ambiguity_level="low")

    def _assess_impl(self, task_def: TaskDefinition) -> ExecutionReadiness:
        """Core assessment logic (no timeout wrapper)."""
        ambiguity = self._compute_ambiguity(task_def)
        blocking, non_blocking = self._classify_questions(task_def)

        # Sort by priority
        blocking.sort(key=lambda q: _PRIORITY_ORDER.index(q.priority))

        # Cap at first-round limit
        capped = blocking[:_MAX_FIRST_ROUND]

        # Non-blocking → suggested assumptions
        suggested = self._to_assumptions(non_blocking)

        # Determine status
        if capped:
            status = "blocked"
        elif suggested:
            status = "conditional"
        else:
            status = "ready"

        return ExecutionReadiness(
            status=status,
            blocking_questions=capped,
            suggested_assumptions=suggested,
            ambiguity_level=ambiguity,
        )

    # ------------------------------------------------------------------
    # Ambiguity computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_ambiguity(task_def: TaskDefinition) -> str:
        """Compute ambiguity level based on unknown/low-confidence ratios."""
        all_items = (
            [task_def.objective]
            + list(task_def.deliverables)
            + task_def.constraints
            + task_def.acceptance_criteria
        )
        total = len(all_items)
        if total == 0:
            return "low"

        unknown_count = sum(1 for item in all_items if item.source == FieldSource.UNKNOWN)
        unknown_ratio = unknown_count / total

        # Low-confidence assumptions ratio
        assumptions = task_def.assumptions or []
        low_conf_count = sum(1 for a in assumptions if a.confidence_level == "low")
        low_conf_ratio = low_conf_count / len(assumptions) if assumptions else 0.0

        if unknown_ratio > 0.3 or low_conf_ratio > 0.5:
            return "high"
        if unknown_ratio > 0.1 or low_conf_ratio > 0.2:
            return "medium"
        return "low"

    # ------------------------------------------------------------------
    # Question classification
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_questions(
        task_def: TaskDefinition,
    ) -> tuple:
        """Classify open_questions into blocking and non_blocking lists."""
        blocking: List[BlockingQuestion] = []
        non_blocking: List[str] = []

        for q in task_def.open_questions:
            q_lower = q.lower()

            # Determine priority based on content markers
            if "objective" in q_lower or "目标" in q_lower or "affects_objective" in q_lower:
                blocking.append(BlockingQuestion(
                    question=q, priority=QuestionPriority.AFFECTS_OBJECTIVE,
                    related_field="objective",
                ))
            elif "deliverable" in q_lower or "交付" in q_lower or "产出" in q_lower:
                blocking.append(BlockingQuestion(
                    question=q, priority=QuestionPriority.AFFECTS_DELIVERABLE,
                    related_field="deliverables",
                ))
            elif "high-risk" in q_lower or "高风险" in q_lower or "requires approval" in q_lower:
                blocking.append(BlockingQuestion(
                    question=q, priority=QuestionPriority.AFFECTS_HIGH_RISK,
                    related_field="risks",
                ))
            elif "unknown" in q_lower or "[unknown]" in q_lower:
                blocking.append(BlockingQuestion(
                    question=q, priority=QuestionPriority.OTHER_BLOCKING,
                ))
            else:
                non_blocking.append(q)

        return blocking, non_blocking

    # ------------------------------------------------------------------
    # Assumption conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _to_assumptions(non_blocking: List[str]) -> List[Assumption]:
        """Convert non-blocking questions to suggested assumptions."""
        return [
            Assumption(
                text=q,
                source=FieldSource.INFERRED,
                description=q,
                confidence_level="medium",
            )
            for q in non_blocking
        ]
