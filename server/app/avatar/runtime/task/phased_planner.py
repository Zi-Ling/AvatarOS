"""
PhasedPlanner — goal-oriented phased execution planning.

Data models (PhasePlan, GoalPlan) + PhasedPlanner logic:
- should_activate: trigger condition check
- plan: generate GoalPlan from TaskDefinition
- execute: linear phase execution with acceptance verification
- PhaseAcceptancePolicy: structured acceptance evaluation
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
# Max recursion depth for phased planning (prevent infinite decomposition)
MAX_PHASED_DEPTH = 1
# Max recent phase summaries to carry forward (prevent context bloat)
MAX_CONTEXT_SUMMARIES = 3


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


# ---------------------------------------------------------------------------
# Phase acceptance evaluation
# ---------------------------------------------------------------------------

@dataclass
class PhaseAcceptanceResult:
    """Structured result from phase acceptance evaluation."""
    accepted: bool
    reason: str
    failure_type: str = "none"  # "none" / "execution_error" / "business_unmet"
    artifact_paths: List[str] = field(default_factory=list)
    summary: Optional[str] = None


class PhaseAcceptancePolicy:
    """Evaluate whether a phase execution result meets acceptance criteria.

    Separates "execution exception" from "business not met" so retry/degrade
    logic can make informed decisions.
    """

    @staticmethod
    def evaluate(result: Any, phase: "PhasePlan") -> PhaseAcceptanceResult:
        """Evaluate an ExecutionResult against phase acceptance criteria.

        Returns PhaseAcceptanceResult with structured failure reason.
        """
        # Extract artifact paths from graph if available
        artifact_paths: List[str] = []
        summary: Optional[str] = None
        if hasattr(result, "graph") and result.graph is not None:
            for node in result.graph.nodes.values():
                outputs = getattr(node, "outputs", None) or {}
                for p in outputs.get("__artifact_paths__", []):
                    if isinstance(p, str):
                        artifact_paths.append(p)
        if hasattr(result, "summary"):
            summary = result.summary

        # Check 1: ExecutionResult.success flag
        if hasattr(result, "success") and not result.success:
            final_status = getattr(result, "final_status", "unknown")
            error_msg = getattr(result, "error_message", None) or f"status={final_status}"
            return PhaseAcceptanceResult(
                accepted=False,
                reason=error_msg,
                failure_type="execution_error",
                artifact_paths=artifact_paths,
                summary=summary,
            )

        # Check 2: partial_success — execution ran but not all nodes succeeded
        if hasattr(result, "final_status") and result.final_status == "partial_success":
            failed_count = getattr(result, "failed_nodes", 0)
            return PhaseAcceptanceResult(
                accepted=False,
                reason=f"partial_success: {failed_count} nodes failed",
                failure_type="business_unmet",
                artifact_paths=artifact_paths,
                summary=summary,
            )

        # Accepted
        return PhaseAcceptanceResult(
            accepted=True,
            reason="ok",
            artifact_paths=artifact_paths,
            summary=summary,
        )


class PhasedPlanner:
    """Goal-oriented phased execution planner.

    Activates for complex tasks that benefit from phased decomposition.
    Each phase is executed independently via GraphController (ReAct mode).

    Activation signal comes from ComplexityResult.estimated_phases (LLM-derived),
    NOT from TaskDefinition.deliverables (which may be empty if extractor is absent).
    """

    def should_activate(
        self,
        complexity: Any,
        task_def: Any = None,
        readiness: Optional[Any] = None,
        env_context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Check if phased planning should activate.

        Primary signal: ComplexityResult.estimated_phases >= 3
        Secondary signal (if TaskDefinition available): deliverables > 3
        Guard: recursion depth must be < MAX_PHASED_DEPTH

        Returns activation decision and logs the reason for observability.
        """
        if getattr(complexity, "task_type", None) != "complex":
            logger.debug("[PhasedPlanner] reject: task_type=%s (not complex)", getattr(complexity, "task_type", None))
            return False

        # Recursion depth guard — prevent infinite decomposition
        ctx = env_context or {}
        current_depth = ctx.get("_phased_depth", 0)
        if current_depth >= MAX_PHASED_DEPTH:
            logger.info(
                "[PhasedPlanner] reject: recursion depth %d >= limit %d, falling back to ReAct",
                current_depth, MAX_PHASED_DEPTH,
            )
            return False

        estimated_phases = getattr(complexity, "estimated_phases", 1)
        phase_hints = getattr(complexity, "phase_hints", [])

        # Primary: LLM estimated phases
        if estimated_phases >= 3:
            logger.info(
                "[PhasedPlanner] activated: estimated_phases=%d, hints=%s, depth=%d",
                estimated_phases, phase_hints[:5], current_depth,
            )
            return True

        # Secondary: structured deliverables (if TaskDefinition available)
        if task_def is not None:
            deliverables = getattr(task_def, "deliverables", [])
            if len(deliverables) > 3:
                logger.info("[PhasedPlanner] activated: %d deliverables from TaskDefinition, depth=%d", len(deliverables), current_depth)
                return True

        logger.debug(
            "[PhasedPlanner] reject: estimated_phases=%d, phase_hints=%d, deliverables=%d, depth=%d",
            estimated_phases, len(phase_hints),
            len(getattr(task_def, "deliverables", [])) if task_def else 0,
            current_depth,
        )
        return False

    async def plan(
        self,
        complexity: Any,
        intent: str,
        task_def: Any = None,
    ) -> GoalPlan:
        """Generate a GoalPlan from ComplexityResult phase hints.

        Priority:
        1. ComplexityResult.phase_hints (LLM-derived, preferred)
        2. TaskDefinition.deliverables (structured, fallback)
        3. Single-phase fallback with full intent
        """
        phase_hints: List[str] = getattr(complexity, "phase_hints", [])
        estimated_phases: int = getattr(complexity, "estimated_phases", 1)

        phases: List[PhasePlan] = []
        prev_id: Optional[str] = None

        if phase_hints:
            # Build from LLM phase hints
            for i, hint in enumerate(phase_hints):
                phase_id = f"phase_{i}"
                phases.append(PhasePlan(
                    phase_id=phase_id,
                    phase_objective=hint,
                    phase_deliverables=[hint],
                    phase_acceptance_criteria=[f"{hint} is complete and verified"],
                    predecessor_phase_id=prev_id,
                ))
                prev_id = phase_id
        elif task_def is not None and getattr(task_def, "deliverables", []):
            # Fallback: build from TaskDefinition deliverables
            for i, d in enumerate(getattr(task_def, "deliverables", [])):
                phase_id = f"phase_{i}"
                d_name = getattr(d, "name", "") or getattr(d, "text", f"deliverable_{i}")
                d_desc = getattr(d, "description", "") or d_name
                phases.append(PhasePlan(
                    phase_id=phase_id,
                    phase_objective=f"Complete: {d_name}",
                    phase_deliverables=[d_desc],
                    phase_acceptance_criteria=[f"{d_name} is complete and verified"],
                    predecessor_phase_id=prev_id,
                ))
                prev_id = phase_id
        else:
            # Last resort: single phase with full intent
            phases.append(PhasePlan(
                phase_id="phase_0",
                phase_objective=intent,
                phase_deliverables=[intent],
                phase_acceptance_criteria=[f"{intent} — completed"],
            ))

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

        return GoalPlan(
            phases=phases,
            global_acceptance_criteria=[f"{intent} — all phases complete"],
            estimated_total_phases=len(phases),
        )

    async def execute(
        self,
        goal_plan: GoalPlan,
        graph_controller: GraphControllerProtocol,
        env_context: Optional[Dict[str, Any]] = None,
        config: Any = None,
    ) -> "ExecutionResult":
        """Execute phases linearly, returning an ExecutionResult compatible
        with GraphController so callers (main.py) need no special-casing.

        For each phase:
        1. Mark in_progress
        2. Execute via GraphController
        3. Evaluate acceptance via PhaseAcceptancePolicy
        4. Retry up to MAX_PHASE_RETRIES if not accepted
        5. Relay context (summary + artifact refs) to next phase
        """
        from app.avatar.runtime.graph.runtime.graph_runtime import ExecutionResult

        ctx = env_context or {}
        current_depth = ctx.get("_phased_depth", 0)
        results: List[Dict[str, Any]] = []
        total = len(goal_plan.phases)
        t0 = time.monotonic()
        last_graph: Any = None

        # Phase context relay: accumulate summaries + artifact refs for downstream phases
        phase_context_chain: List[Dict[str, Any]] = []

        # Item 4: phase event publisher (decoupled from NarrativeManager)
        # Caller injects async callback via env_context; PhasedPlanner doesn't
        # know about WebSocket/Narrative/trace — just calls the callback.
        _emit_phase_event = ctx.get("_phase_event_callback")

        for phase in goal_plan.phases:
            phase.status = "in_progress"
            phase_idx = goal_plan.phases.index(phase)

            # Emit phase.start event
            if _emit_phase_event:
                try:
                    await _emit_phase_event(
                        "phase.start", phase.phase_id,
                        f"正在执行第 {phase_idx + 1}/{total} 阶段：{phase.phase_objective}",
                    )
                except Exception:
                    pass  # non-critical

            phase_ctx = {
                **ctx,
                "phase_id": phase.phase_id,
                "_phased_depth": current_depth + 1,
                "_skip_complexity": True,
            }

            # ── Item 7: inject previous phase context ───────────────
            if phase_context_chain:
                phase_ctx["_previous_phases"] = phase_context_chain[-MAX_CONTEXT_SUMMARIES:]

            # Build scoped intent with context relay
            parent_intent = ctx.get("_phased_parent_intent", "")
            scoped_intent = (
                f"[Phase {phase_idx + 1}/{total}] {phase.phase_objective}"
                f"\n\nThis is one phase of a larger task"
                + (f": '{parent_intent}'" if parent_intent else "")
                + ". Execute this phase directly — do NOT decompose into sub-phases."
            )
            # Append previous phase summaries + artifact refs to scoped intent
            if phase_context_chain:
                recent = phase_context_chain[-MAX_CONTEXT_SUMMARIES:]
                context_lines = []
                for pc in recent:
                    line = f"- Phase {pc['phase_index']}: {pc['summary']}"
                    if pc.get("artifact_paths"):
                        line += f" [files: {', '.join(pc['artifact_paths'][:5])}]"
                    if pc.get("pending_items"):
                        line += f" [pending: {', '.join(pc['pending_items'][:3])}]"
                    context_lines.append(line)
                scoped_intent += "\n\nCompleted phases:\n" + "\n".join(context_lines)

            phase_ctx["_phased_parent_intent"] = phase.phase_objective

            # ── Execute with acceptance evaluation ──────────────────
            acceptance: Optional[PhaseAcceptanceResult] = None
            for attempt in range(1 + MAX_PHASE_RETRIES):
                try:
                    result = await graph_controller.execute(
                        intent=scoped_intent,
                        env_context=phase_ctx,
                        config=config,
                    )
                    # Structured acceptance check (item 3)
                    acceptance = PhaseAcceptancePolicy.evaluate(result, phase)

                    if hasattr(result, "graph"):
                        last_graph = result.graph

                    if acceptance.accepted:
                        phase.status = "completed"
                        phase.phase_summary = (
                            acceptance.summary
                            or f"Phase {phase.phase_id} completed on attempt {attempt + 1}"
                        )
                        # Emit phase.completed event
                        if _emit_phase_event:
                            try:
                                await _emit_phase_event(
                                    "phase.completed", phase.phase_id,
                                    f"第 {phase_idx + 1}/{total} 阶段完成",
                                )
                            except Exception:
                                pass
                        # Build context relay entry for downstream phases
                        phase_context_chain.append({
                            "phase_index": phase_idx + 1,
                            "objective": phase.phase_objective,
                            "summary": phase.phase_summary,
                            "artifact_paths": acceptance.artifact_paths,
                            "pending_items": [],  # V2: extract from acceptance
                        })
                        results.append({
                            "phase_id": phase.phase_id,
                            "status": "completed",
                            "attempts": attempt + 1,
                        })
                        break
                    else:
                        # Business not met — log and retry
                        logger.warning(
                            "Phase %s attempt %d not accepted (%s): %s",
                            phase.phase_id, attempt + 1,
                            acceptance.failure_type, acceptance.reason,
                        )
                        if attempt >= MAX_PHASE_RETRIES:
                            phase.status = "failed"
                            phase.phase_summary = (
                                f"Phase {phase.phase_id} not accepted after "
                                f"{attempt + 1} attempts: {acceptance.reason}"
                            )
                            results.append({
                                "phase_id": phase.phase_id,
                                "status": "failed",
                                "attempts": attempt + 1,
                                "error": acceptance.reason,
                                "failure_type": acceptance.failure_type,
                            })

                except Exception as exc:
                    logger.warning(
                        "Phase %s attempt %d exception: %s",
                        phase.phase_id, attempt + 1, exc,
                    )
                    if attempt >= MAX_PHASE_RETRIES:
                        phase.status = "failed"
                        phase.phase_summary = (
                            f"Phase {phase.phase_id} failed after {attempt + 1} attempts: {exc}"
                        )
                        results.append({
                            "phase_id": phase.phase_id,
                            "status": "failed",
                            "attempts": attempt + 1,
                            "error": str(exc),
                            "failure_type": "execution_error",
                        })

            if phase.status == "failed":
                logger.error("Phase %s failed, halting execution", phase.phase_id)
                if _emit_phase_event:
                    try:
                        await _emit_phase_event(
                            "phase.failed", phase.phase_id,
                            f"第 {phase_idx + 1}/{total} 阶段失败",
                        )
                    except Exception:
                        pass
                break

        elapsed = time.monotonic() - t0
        all_completed = all(r["status"] == "completed" for r in results)
        completed_count = sum(1 for r in results if r["status"] == "completed")
        failed_count = sum(1 for r in results if r["status"] == "failed")

        return ExecutionResult(
            success=all_completed,
            final_status="completed" if all_completed else "failed",
            completed_nodes=completed_count,
            failed_nodes=failed_count,
            execution_time=elapsed,
            error_message=None if all_completed else f"{failed_count}/{total} phases failed",
            graph=last_graph,
            summary=f"PhasedPlanner: {completed_count}/{total} phases completed in {elapsed:.1f}s",
        )
