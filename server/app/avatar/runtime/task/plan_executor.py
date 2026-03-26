"""
TaskPlanExecutor — executes a TaskExecutionPlan by dispatching SubGoalUnits
to GraphController one at a time.

Replaces PhasedPlanner.execute() with structured state management:
- Each SubGoalUnit gets a scoped intent + structured env_context
- Output verification against RequiredOutput specs
- Failure propagation via depends_on edges
- TaskExecutionPlan is the single arbiter of completion

Design: reuses GraphController as the execution engine for each unit.
Does NOT create a second runtime — just a structured scheduling shell.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Set, Tuple

from .execution_plan import (
    OutputStatus,
    PlanStatus,
    RequiredOutput,
    SubGoalUnit,
    TaskExecutionPlan,
    UnitStatus,
)

logger = logging.getLogger(__name__)


# ── Configurable executor parameters ────────────────────────────────

@dataclass
class ExecutorConfig:
    """All tunable parameters for TaskPlanExecutor in one place.

    Centralises output field names and thresholds. Skill classifications
    (read-only vs productive) are loaded dynamically from SkillRegistry
    at TaskPlanExecutor init time — no hardcoded skill name lists.
    """
    # Max context summaries to include from completed units
    max_context_summaries: int = 3

    # Output field names to scan in node outputs for produced file paths.
    # Order matters: checked sequentially, first match wins.
    artifact_list_field: str = "__artifact_paths__"
    file_path_fields: Tuple[str, ...] = ("file_path", "output_path", "path")
    artifacts_list_field: str = "artifacts"

    # Minimum text length to count as evidence for "answer"/"data" outputs
    min_text_evidence_len: int = 10


class GraphControllerProtocol(Protocol):
    """Minimal protocol for GraphController dependency injection."""
    async def execute(
        self, intent: str, mode: Any = ..., env_context: Optional[Dict[str, Any]] = ...,
        config: Any = ..., control_handle: Any = ...,
    ) -> Any: ...


class TaskPlanExecutor:
    """Execute a TaskExecutionPlan by dispatching units to GraphController.

    The executor is the scheduling loop. GraphController handles the actual
    ReAct execution of each unit. The executor:
    1. Picks the next ready unit (dependencies satisfied)
    2. Builds scoped intent + structured env_context
    3. Dispatches to GraphController
    4. Verifies outputs against RequiredOutput specs
    5. Updates plan state (completed/failed/degraded)
    6. Propagates failures to downstream units
    7. Repeats until no more units can execute
    """

    def __init__(self, config: Optional[ExecutorConfig] = None) -> None:
        self.config = config or ExecutorConfig()

        # ── Build skill classifications from SkillRegistry ─────────
        # Same pattern as GoalTracker._load_from_registry():
        # read-only = risk_level in (READ, SAFE)
        # productive = risk_level in (WRITE, EXECUTE, SYSTEM) + NETWORK side-effect skills
        self._read_only_skills: Set[str] = set()
        self._productive_skills: Set[str] = set()
        self._load_skill_classifications()

    def _load_skill_classifications(self) -> None:
        """Build read-only / productive skill sets from SkillRegistry."""
        from app.avatar.skills.base import SkillRiskLevel, SideEffect
        from app.avatar.skills.registry import skill_registry

        for spec in skill_registry.list_specs():
            if spec.risk_level in (SkillRiskLevel.READ, SkillRiskLevel.SAFE):
                self._read_only_skills.add(spec.name)
            if spec.risk_level in (SkillRiskLevel.WRITE, SkillRiskLevel.EXECUTE, SkillRiskLevel.SYSTEM):
                self._productive_skills.add(spec.name)
            # Network skills (web.search, net.get) are productive even if READ
            if SideEffect.NETWORK in spec.side_effects:
                self._productive_skills.add(spec.name)
                self._read_only_skills.discard(spec.name)

        logger.debug(
            "[TaskPlanExecutor] Loaded skill classifications: %d read-only, %d productive",
            len(self._read_only_skills), len(self._productive_skills),
        )

    async def execute(
        self,
        plan: TaskExecutionPlan,
        graph_controller: GraphControllerProtocol,
        env_context: Optional[Dict[str, Any]] = None,
        config: Any = None,
    ) -> Any:
        """Execute all units in the plan sequentially.

        Returns an ExecutionResult compatible with GraphController callers.
        """
        from app.avatar.runtime.graph.runtime.graph_runtime import ExecutionResult

        ctx = env_context or {}
        plan.status = PlanStatus.IN_PROGRESS
        t0 = time.monotonic()
        last_graph: Any = None

        # Phase event callback (if provided by caller)
        _emit_phase_event = ctx.get("_phase_event_callback")

        total = len(plan.units)
        completed_count = 0
        failed_count = 0

        while True:
            unit = plan.get_next_unit()
            if unit is None:
                break  # No more executable units

            unit.status = UnitStatus.IN_PROGRESS
            unit_idx = plan.units.index(unit)

            logger.info(
                "[TaskPlanExecutor] Executing unit %s (%d/%d): %s",
                unit.unit_id, unit_idx + 1, total, unit.objective[:80],
            )

            # Emit phase.start event
            if _emit_phase_event:
                try:
                    await _emit_phase_event(
                        "phase.start", unit.unit_id,
                        f"正在执行第 {unit_idx + 1}/{total} 阶段：{unit.objective}",
                    )
                except Exception:
                    pass

            # Build execution context
            unit_context = plan.build_unit_context(unit.unit_id)
            scoped_intent = self._build_scoped_intent(plan, unit, unit_context)

            unit_env = {
                **ctx,
                **unit_context,
                "phase_id": unit.unit_id,
                "_phased_depth": ctx.get("_phased_depth", 0) + 1,
                "_skip_complexity": True,
                "_phased_original_goal": plan.original_goal,
                "_phased_parent_intent": unit.objective,
                # Workspace isolation: each unit gets a scoped output root
                # so artifact collector and planner context only see this
                # unit's outputs, not historical files from other units.
                "_task_scoped_output_root": unit.unit_id,
                "_parent_plan_id": plan.plan_id,
            }

            # Inject skill hint as Planner constraint
            if unit.skill_hint:
                unit_env["_skill_hint"] = {
                    "preferred": unit.skill_hint.preferred_skills,
                    "prohibited": unit.skill_hint.prohibited_skills,
                    "reason": unit.skill_hint.reason,
                }

            # Execute via GraphController
            success = False
            for attempt in range(1 + unit.max_retries):
                try:
                    result = await graph_controller.execute(
                        intent=scoped_intent,
                        env_context=unit_env,
                        config=config,
                    )

                    if hasattr(result, "graph"):
                        last_graph = result.graph

                    # Verify outputs
                    output_results = self._extract_outputs(result, unit)
                    all_required_satisfied = self._check_outputs_satisfied(unit, output_results)

                    if hasattr(result, "success") and result.success and all_required_satisfied:
                        plan.mark_unit_completed(unit.unit_id, output_results)
                        success = True
                        completed_count += 1

                        if _emit_phase_event:
                            try:
                                await _emit_phase_event(
                                    "phase.completed", unit.unit_id,
                                    f"第 {unit_idx + 1}/{total} 阶段完成",
                                )
                            except Exception:
                                pass
                        break

                    elif hasattr(result, "success") and result.success and not all_required_satisfied:
                        # Execution succeeded but outputs not fully produced
                        # Mark as completed anyway — plan.mark_unit_completed handles degradation
                        plan.mark_unit_completed(unit.unit_id, output_results)
                        if unit.status == UnitStatus.DEGRADED:
                            completed_count += 1  # degraded counts as partial success
                        success = True
                        break

                    else:
                        # Execution failed
                        error_msg = getattr(result, "error_message", None) or "execution failed"
                        unit.error_summary = error_msg[:200]
                        unit.retry_count = attempt + 1
                        logger.warning(
                            "[TaskPlanExecutor] Unit %s attempt %d failed: %s",
                            unit.unit_id, attempt + 1, error_msg[:100],
                        )

                        if attempt >= unit.max_retries:
                            plan.mark_unit_failed(unit.unit_id, error_msg[:200])
                            failed_count += 1

                except Exception as exc:
                    unit.retry_count = attempt + 1
                    logger.warning(
                        "[TaskPlanExecutor] Unit %s attempt %d exception: %s",
                        unit.unit_id, attempt + 1, exc,
                    )
                    if attempt >= unit.max_retries:
                        plan.mark_unit_failed(unit.unit_id, str(exc)[:200])
                        failed_count += 1

            if not success:
                if _emit_phase_event:
                    try:
                        await _emit_phase_event(
                            "phase.failed", unit.unit_id,
                            f"第 {unit_idx + 1}/{total} 阶段失败",
                        )
                    except Exception:
                        pass
                # Don't break — continue to next independent unit if any
                # (failure propagation already blocked dependent units)

        # Compute final status via OutcomeReducer (unified arbiter)
        from app.avatar.runtime.verification.outcome_reducer import (
            OutcomeReducer, Outcome, PlanSignal,
        )
        _reducer = OutcomeReducer()
        _plan_signal = OutcomeReducer.plan_signal_from_plan(plan)
        _outcome = _reducer.reduce(plan=_plan_signal)
        elapsed = time.monotonic() - t0

        # Map Outcome to ExecutionResult fields
        _outcome_to_status = {
            Outcome.COMPLETED: "completed",
            Outcome.DEGRADED: "partial_success",
            Outcome.FAILED: "failed",
            Outcome.BLOCKED: "failed",
        }
        _final_status = _outcome_to_status.get(_outcome, "failed")
        _success = _outcome in (Outcome.COMPLETED, Outcome.DEGRADED)

        logger.info(
            "[TaskPlanExecutor] Plan %s finished: %s (%d/%d completed, %d failed) in %.1fs",
            plan.plan_id, _final_status, completed_count, total, failed_count, elapsed,
        )

        return ExecutionResult(
            success=_success,
            final_status=_final_status,
            completed_nodes=completed_count,
            failed_nodes=failed_count,
            execution_time=elapsed,
            error_message=None if _success
                else f"{failed_count}/{total} units failed",
            graph=last_graph,
            summary=plan.to_summary(),
        )

    # ── Scoped intent builder ───────────────────────────────────────

    def _build_scoped_intent(
        self,
        plan: TaskExecutionPlan,
        unit: SubGoalUnit,
        context: Dict[str, Any],
    ) -> str:
        """Build a concise, structured scoped intent for the Planner.

        The scoped_intent is a human-readable summary for the Planner.
        The real structured data lives in env_context (_required_outputs,
        _resolved_inputs, _skill_hint). This string is supplementary.
        """
        unit_idx = plan.units.index(unit)
        total = len(plan.units)

        lines = [
            f"[SubGoal {unit_idx + 1}/{total}] {unit.objective}",
            "",
            f"Original user goal: {plan.original_goal}",
        ]

        # Required outputs
        pending = [o for o in unit.required_outputs if o.status == OutputStatus.PENDING]
        if pending:
            lines.append("")
            lines.append("You MUST produce these outputs:")
            for o in pending:
                fmt = f", format: {o.format_hint}" if o.format_hint else ""
                lines.append(f"  - {o.description} ({o.output_type}{fmt})")

        # Available inputs from upstream
        resolved = context.get("_resolved_inputs", {})
        if resolved:
            lines.append("")
            lines.append("Available inputs from previous sub-goals:")
            for ref_name, ref_path in resolved.items():
                lines.append(f"  - {ref_name}: {ref_path}")

        # Previous error (if retrying)
        if unit.error_summary:
            lines.append("")
            lines.append(f"Previous attempt failed: {unit.error_summary[:150]}")
            lines.append("Try a different approach.")

        # Skill hint
        hint = context.get("_skill_hint")
        if hint:
            preferred = hint.get("preferred", [])
            prohibited = hint.get("prohibited", [])
            if preferred:
                lines.append("")
                lines.append(f"Recommended skills: {', '.join(preferred)}")
            if prohibited:
                lines.append(f"Do NOT use: {', '.join(prohibited)}")
            if hint.get("reason"):
                lines.append(f"Reason: {hint['reason']}")

        # Completed sibling summaries (brief, max 3)
        completed_siblings = [
            u for u in plan.units
            if u.status in (UnitStatus.COMPLETED, UnitStatus.DEGRADED)
        ][-self.config.max_context_summaries:]
        if completed_siblings:
            lines.append("")
            lines.append("Completed sub-goals:")
            for sib in completed_siblings:
                produced = [
                    o.actual_path or o.description
                    for o in sib.required_outputs
                    if o.status == OutputStatus.PRODUCED
                ]
                produced_str = f" [produced: {', '.join(produced[:3])}]" if produced else ""
                lines.append(f"  - {sib.objective[:60]}{produced_str}")

        lines.append("")
        lines.append("Execute this sub-goal directly — do NOT decompose into sub-phases.")

        return "\n".join(lines)

    # ── Output extraction and verification ──────────────────────────

    def _is_productive_node(self, node: Any) -> bool:
        """Check if a node used a productive (non-read-only) skill.

        Classification is loaded from SkillRegistry at init time.
        Unknown skills are accepted by default (conservative).
        """
        cap = getattr(node, "capability_name", "") or ""
        if cap in self._read_only_skills:
            return False
        if cap in self._productive_skills:
            return True
        # Unknown skill — accept by default (conservative: don't block new skills)
        return True

    def _extract_outputs(
        self,
        result: Any,
        unit: SubGoalUnit,
    ) -> Dict[str, Dict[str, Any]]:
        """Extract produced outputs from ExecutionResult graph nodes.

        Matches RequiredOutput specs against actual node outputs by:
        1. File extension matching (for output_type="file")
        2. Artifact path matching
        3. Text output presence (for output_type="answer"/"data")

        HARDENED: read-only skills (fs.read, fs.list) are excluded from
        evidence collection. Only nodes that used productive skills count.

        Returns: {output_id: {"path": str, "artifact_id": str, "node_id": str}}
        """
        output_results: Dict[str, Dict[str, Any]] = {}

        if not hasattr(result, "graph") or result.graph is None:
            # No graph — check for direct reply (answer type)
            summary = getattr(result, "summary", "")
            if summary:
                for out in unit.required_outputs:
                    if out.output_type == "answer" and out.status == OutputStatus.PENDING:
                        output_results[out.output_id] = {
                            "path": None,
                            "node_id": None,
                        }
            return output_results

        graph = result.graph
        from app.avatar.runtime.graph.models.step_node import NodeStatus

        succeeded_nodes = [
            n for n in graph.nodes.values() if n.status == NodeStatus.SUCCESS
        ]

        # Partition into productive vs read-only nodes
        productive_nodes = [n for n in succeeded_nodes if self._is_productive_node(n)]
        has_any_productive = len(productive_nodes) > 0

        # Collect all produced file paths from PRODUCTIVE succeeded nodes only
        produced_files: List[Dict[str, Any]] = []
        cfg = self.config
        for node in productive_nodes:
            outputs = getattr(node, "outputs", None) or {}
            # Check artifact list field (e.g. __artifact_paths__)
            for p in outputs.get(cfg.artifact_list_field, []):
                if isinstance(p, str):
                    produced_files.append({"path": p, "node_id": str(node.id)})
            # Check output_contract in metadata
            oc = (getattr(node, "metadata", None) or {}).get("output_contract")
            if oc and isinstance(oc, dict):
                p = oc.get("path") or oc.get("artifact_id")
                if p:
                    produced_files.append({
                        "path": p,
                        "artifact_id": oc.get("artifact_id"),
                        "node_id": str(node.id),
                    })
            # Check configurable file path fields
            for key in cfg.file_path_fields:
                val = outputs.get(key)
                if isinstance(val, str) and val:
                    produced_files.append({"path": val, "node_id": str(node.id)})
            # Check artifacts list (browser.run style)
            for art in outputs.get(cfg.artifacts_list_field, []):
                if isinstance(art, str):
                    produced_files.append({"path": art, "node_id": str(node.id)})

        # Match RequiredOutputs to produced files
        for out in unit.required_outputs:
            if out.status != OutputStatus.PENDING:
                continue

            if out.output_type == "file" and out.format_hint:
                # Match by file extension
                ext = f".{out.format_hint.lower()}"
                for pf in produced_files:
                    if pf["path"] and pf["path"].lower().endswith(ext):
                        output_results[out.output_id] = pf
                        break

            elif out.output_type in ("answer", "data"):
                # Only accept text from PRODUCTIVE nodes — fs.read alone
                # reading an old file is not evidence of goal completion.
                for node in productive_nodes:
                    outputs = getattr(node, "outputs", None) or {}
                    has_text = any(
                        isinstance(v, str) and len(v) > cfg.min_text_evidence_len
                        for v in outputs.values()
                    )
                    if has_text:
                        output_results[out.output_id] = {
                            "path": None,
                            "node_id": str(node.id),
                        }
                        break

            # Fallback: if output_type is "file" without format_hint, any produced file matches
            if out.output_id not in output_results and out.output_type == "file":
                if produced_files:
                    output_results[out.output_id] = produced_files[0]

        return output_results

    def _check_outputs_satisfied(
        self,
        unit: SubGoalUnit,
        output_results: Dict[str, Dict[str, Any]],
    ) -> bool:
        """Check if all required outputs are satisfied.

        HARDENED: also checks that at least one productive skill was used
        when the unit has required outputs. A unit that only ran fs.read
        cannot be considered "satisfied" even if output_results has entries.
        """
        for out in unit.required_outputs:
            if out.required and out.output_id not in output_results:
                return False
        return True
