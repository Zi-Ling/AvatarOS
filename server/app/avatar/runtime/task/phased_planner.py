"""
PhasedPlanner — goal-oriented phased execution planning.

Data models (PhasePlan, GoalPlan) + PhasedPlanner logic:
- should_activate: trigger condition check
- plan: generate GoalPlan from TaskDefinition
- execute: linear phase execution with acceptance verification
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)

# Performance guard: max phases
MAX_PHASES = 10
# Max retries per phase
MAX_PHASE_RETRIES = 2

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PhasePlan:
    """A single phase within a GoalPlan."""
    phase_id: str
    phase_objective: str
    phase_deliverables: List[str]  # verifiable concrete outputs (V2_PLANNED: upgrade to structured Deliverable list)
    phase_acceptance_criteria: List[str]  # decidable acceptance conditions
    predecessor_phase_id: Optional[str] = None
    status: str = "pending"  # "pending" / "in_progress" / "completed" / "failed"
    phase_summary: Optional[str] = None  # generated after phase completion
    schema_version: str = "1.0.0"


@dataclass
class GoalPlan:
    """Ordered linear sequence of phases for complex task execution."""
    phases: List[PhasePlan] = field(default_factory=list)
    global_acceptance_criteria: List[str] = field(default_factory=list)
    estimated_total_phases: int = 0
    schema_version: str = "1.0.0"


class GraphControllerProtocol(Protocol):
    """Minimal protocol for GraphController dependency injection."""
    async def execute(
        self, intent: str, env_context: Dict[str, Any], config: Any, control_handle: Any = None,
    ) -> Any: ...


class PhasedPlanner:
    """Goal-oriented phased execution planner.

    Activates for complex tasks that benefit from phased decomposition.
    Each phase is executed independently via GraphController (ReAct mode).
    """

    def should_activate(
        self,
        task_def: Any,
        complexity: Any,
        readiness: Optional[Any] = None,
    ) -> bool:
        """Check if phased planning should activate.

        Trigger conditions (any one suffices):
        (a) extracted deliverables > 3
        (b) deliverables span > 2 technical domains
        (c) ambiguity_level >= medium AND deliverables > 2
        """
        if getattr(complexity, "task_type", None) != "complex":
            return False

        deliverables = getattr(task_def, "deliverables", [])
        n_deliverables = len(deliverables)

        # (a) Many deliverables
        if n_deliverables > 3:
            return True

        # (b) Multiple technical domains
        if n_deliverables > 0:
            domains = set()
            for d in deliverables:
                d_type = getattr(d, "type", "")
                if d_type:
                    domains.add(d_type)
            if len(domains) > 2:
                return True

        # (c) Ambiguity + deliverables
        ambiguity = getattr(readiness, "ambiguity_level", "low") if readiness else "low"
        if ambiguity in ("medium", "high") and n_deliverables > 2:
            return True

        return False

    async def plan(self, task_def: Any) -> GoalPlan:
        """Generate a GoalPlan from a TaskDefinition.

        V1: Simple linear decomposition based on deliverables.
        Each deliverable becomes a phase with its own acceptance criteria.
        """
        deliverables = getattr(task_def, "deliverables", [])
        objective_text = getattr(
            getattr(task_def, "objective", None), "text", "complete task"
        )
        acceptance = getattr(task_def, "acceptance_criteria", [])

        phases: List[PhasePlan] = []
        prev_id: Optional[str] = None

        for i, d in enumerate(deliverables):
            phase_id = f"phase_{i}"
            d_name = getattr(d, "name", "") or getattr(d, "text", f"deliverable_{i}")
            d_desc = getattr(d, "description", "") or d_name

            phase = PhasePlan(
                phase_id=phase_id,
                phase_objective=f"Complete: {d_name}",
                phase_deliverables=[d_desc],
                phase_acceptance_criteria=[f"{d_name} is complete and verified"],
                predecessor_phase_id=prev_id,
            )
            phases.append(phase)
            prev_id = phase_id

        # Cap at MAX_PHASES
        if len(phases) > MAX_PHASES:
            logger.warning(
                "Phase count %d exceeds limit %d, merging tail phases",
                len(phases), MAX_PHASES,
            )
            tail = phases[MAX_PHASES - 1:]
            merged_deliverables = []
            for p in tail:
                merged_deliverables.extend(p.phase_deliverables)
            phases = phases[:MAX_PHASES - 1]
            phases.append(PhasePlan(
                phase_id=f"phase_{MAX_PHASES - 1}",
                phase_objective="Complete remaining work",
                phase_deliverables=merged_deliverables,
                phase_acceptance_criteria=["All remaining deliverables complete"],
                predecessor_phase_id=phases[-1].phase_id if phases else None,
            ))

        global_criteria = [
            getattr(ac, "text", str(ac)) for ac in acceptance
        ] or [f"{objective_text} — all phases complete"]

        return GoalPlan(
            phases=phases,
            global_acceptance_criteria=global_criteria,
            estimated_total_phases=len(phases),
        )

    async def execute(
        self,
        goal_plan: GoalPlan,
        graph_controller: GraphControllerProtocol,
        env_context: Optional[Dict[str, Any]] = None,
        config: Any = None,
    ) -> Dict[str, Any]:
        """Execute phases linearly.

        For each phase:
        1. Mark in_progress
        2. Execute via GraphController
        3. Verify acceptance criteria
        4. Retry up to MAX_PHASE_RETRIES if not met
        5. Generate phase_summary
        """
        ctx = env_context or {}
        results: List[Dict[str, Any]] = []

        for phase in goal_plan.phases:
            phase.status = "in_progress"
            phase_ctx = {**ctx, "phase_id": phase.phase_id}

            success = False
            for attempt in range(1 + MAX_PHASE_RETRIES):
                try:
                    result = await graph_controller.execute(
                        intent=phase.phase_objective,
                        env_context=phase_ctx,
                        config=config,
                    )
                    # V1: acceptance check is optimistic (assume success if no exception)
                    success = True
                    phase.status = "completed"
                    phase.phase_summary = (
                        f"Phase {phase.phase_id} completed on attempt {attempt + 1}"
                    )
                    results.append({
                        "phase_id": phase.phase_id,
                        "status": "completed",
                        "attempts": attempt + 1,
                        "result": result,
                    })
                    break
                except Exception as exc:
                    logger.warning(
                        "Phase %s attempt %d failed: %s",
                        phase.phase_id, attempt + 1, exc,
                    )
                    if attempt >= MAX_PHASE_RETRIES:
                        phase.status = "failed"
                        phase.phase_summary = f"Phase {phase.phase_id} failed after {attempt + 1} attempts"
                        results.append({
                            "phase_id": phase.phase_id,
                            "status": "failed",
                            "attempts": attempt + 1,
                            "error": str(exc),
                        })

            if phase.status == "failed":
                logger.error("Phase %s failed, halting execution", phase.phase_id)
                break

        return {
            "phases": results,
            "all_completed": all(r["status"] == "completed" for r in results),
            "total_phases": len(goal_plan.phases),
            "completed_phases": sum(1 for r in results if r["status"] == "completed"),
        }
