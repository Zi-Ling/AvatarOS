"""Auto-distillation: TaskRuntimeState → ProjectMemory.

On task completion, extracts patterns and lessons from TaskRuntimeState
and writes them to ProjectMemory.

- completed_items → ProjectMemory.successful_patterns
- decision_log failure records → ProjectMemory.failure_lessons

Requirements: 2.8
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def distill_to_project_memory(
    task_runtime_state: Any,
    project_memory: Any,
    task_id: str = "",
) -> None:
    """Extract patterns and lessons from TaskRuntimeState into ProjectMemory.

    Called on task completion (apply_decision(COMPLETED) or
    OutcomeTracker.generate_outcome_report()).

    - TaskRuntimeState.completed_items → ProjectMemory.successful_patterns
    - TaskRuntimeState.decision_log failure records → ProjectMemory.failure_lessons

    Requirements: 2.8
    """
    if task_runtime_state is None or project_memory is None:
        return

    try:
        _distill_successful_patterns(task_runtime_state, project_memory, task_id)
        _distill_failure_lessons(task_runtime_state, project_memory, task_id)
        logger.info(
            "[Distillation] Completed distillation for task %s", task_id
        )
    except Exception as exc:
        logger.warning(
            "[Distillation] Failed to distill task %s: %s", task_id, exc
        )


def _distill_successful_patterns(
    task_runtime_state: Any,
    project_memory: Any,
    task_id: str,
) -> None:
    """Extract completed_items as successful patterns."""
    completed_items = getattr(task_runtime_state, "completed_items", []) or []
    for item in completed_items:
        description = getattr(item, "description", str(item))
        update_source = getattr(item, "update_source", None)
        source_value = getattr(update_source, "value", str(update_source)) if update_source else "unknown"
        pattern = {
            "task_id": task_id,
            "description": description,
            "source": source_value,
            "item_id": getattr(item, "item_id", ""),
        }
        try:
            project_memory.record_pattern(pattern)
        except Exception as exc:
            logger.debug("[Distillation] Failed to record pattern: %s", exc)


def _distill_failure_lessons(
    task_runtime_state: Any,
    project_memory: Any,
    task_id: str,
) -> None:
    """Extract failure records from decision_log as failure lessons."""
    decision_log = getattr(task_runtime_state, "decision_log", []) or []
    for entry in decision_log:
        # Identify failure-related decisions
        context = getattr(entry, "context", "")
        decision = getattr(entry, "decision", "")
        rationale = getattr(entry, "rationale", "")

        # Heuristic: entries with failure/error keywords are failure lessons
        combined = f"{context} {decision} {rationale}".lower()
        is_failure = any(
            kw in combined
            for kw in ("fail", "error", "exception", "retry", "fallback", "revert")
        )
        if not is_failure:
            continue

        try:
            project_memory.record_lesson(
                error_context=f"[task:{task_id}] {context}",
                root_cause=decision,
                resolution=rationale,
            )
        except Exception as exc:
            logger.debug("[Distillation] Failed to record lesson: %s", exc)
