"""Integration layer: NegotiationEngine ↔ TaskDefinitionEngine / PhasedPlanner.

- NegotiationEngine.detect_scope_drift() output updates TaskDefinition
- NegotiationEngine.generate_options() user choice updates TaskDefinition
- ProjectIntelligence.organize_milestones() output maps to GoalPlan.PhasePlan

Requirements: 6.7
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def apply_scope_drift_to_task_definition(
    task_definition_engine: Any,
    task_def: Any,
    scope_drift: Dict[str, Any],
) -> Any:
    """Apply scope drift detection result to update TaskDefinition.

    Uses TaskDefinitionEngine.update() to patch the objective when
    drift is detected.

    Returns the updated TaskDefinition.
    """
    if scope_drift is None:
        return task_def

    try:
        current_scope = scope_drift.get("current_scope", {})
        new_objective = current_scope.get("objective", "")
        if new_objective and task_definition_engine is not None:
            from ..task.task_definition import FieldSource
            task_def = task_definition_engine.update(
                task_def,
                field_path="objective",
                new_value=new_objective,
                new_source=FieldSource.INFERRED,
                new_excerpt=f"scope drift: {scope_drift.get('drift_description', '')}",
            )
        logger.info(
            "[NegotiationIntegration] Applied scope drift to TaskDefinition: %s",
            scope_drift.get("drift_description", ""),
        )
    except Exception as exc:
        logger.warning("[NegotiationIntegration] Failed to apply scope drift: %s", exc)

    return task_def


def apply_user_option_choice_to_task_definition(
    task_definition_engine: Any,
    task_def: Any,
    chosen_option: Dict[str, Any],
) -> Any:
    """Apply user's chosen option to update TaskDefinition.

    The chosen option's approach_description is used to refine the objective.

    Returns the updated TaskDefinition.
    """
    if chosen_option is None:
        return task_def

    try:
        approach = chosen_option.get("approach_description", "")
        if approach and task_definition_engine is not None:
            from ..task.task_definition import FieldSource
            current_obj = getattr(task_def, "objective", None)
            current_text = getattr(current_obj, "text", "") if current_obj else ""
            refined = f"{current_text} [approach: {approach}]" if current_text else approach
            task_def = task_definition_engine.update(
                task_def,
                field_path="objective",
                new_value=refined,
                new_source=FieldSource.EXTRACTED,
                new_excerpt=f"user chose: {approach}",
            )
        logger.info(
            "[NegotiationIntegration] Applied user option choice: %s",
            chosen_option.get("approach_description", ""),
        )
    except Exception as exc:
        logger.warning("[NegotiationIntegration] Failed to apply option choice: %s", exc)

    return task_def


def map_milestones_to_goal_plan(
    goal_plan: Any,
    milestones: List[Dict[str, Any]],
) -> Any:
    """Map ProjectIntelligence milestones to GoalPlan.PhasePlan.

    Updates each PhasePlan with milestone metadata from
    ProjectIntelligence.organize_milestones() output.

    Returns the updated GoalPlan.
    """
    if goal_plan is None or not milestones:
        return goal_plan

    try:
        phases = getattr(goal_plan, "phases", []) or []
        ms_by_phase: Dict[str, Dict[str, Any]] = {}
        for ms in milestones:
            ms_id = ms.get("milestone_id", "")
            # milestone_id format: "ms_{phase_id}"
            phase_id = ms_id.replace("ms_", "", 1) if ms_id.startswith("ms_") else ms_id
            ms_by_phase[phase_id] = ms

        for phase in phases:
            phase_id = getattr(phase, "phase_id", "")
            ms = ms_by_phase.get(phase_id)
            if ms is not None:
                # Attach milestone metadata to phase (non-invasive)
                if not hasattr(phase, "_milestone"):
                    object.__setattr__(phase, "_milestone", ms)
                else:
                    phase._milestone = ms  # type: ignore[attr-defined]

        logger.info(
            "[NegotiationIntegration] Mapped %d milestones to GoalPlan",
            len(milestones),
        )
    except Exception as exc:
        logger.warning("[NegotiationIntegration] Failed to map milestones: %s", exc)

    return goal_plan
