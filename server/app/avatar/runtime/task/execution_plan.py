"""
TaskExecutionPlan — structured execution blueprint for complex tasks.

Replaces PhasedPlanner's string-based phase context relay with a
stateful, queryable execution plan. Each SubGoalUnit carries:
- required_outputs bound to the artifact/verifier system
- skill_hints (constraints, not scripts) for Planner guidance
- explicit depends_on for failure propagation
- status state machine managed by TaskPlanExecutor

Design principles (from review feedback):
1. TaskExecutionPlan is a STATE LAYER, not a second Planner.
2. SkillHint is a CONSTRAINT, not a script — expresses "preferred direction"
   and "prohibitions", not step-by-step skill sequences.
3. RequiredOutput maps to the unified artifact/output_contract/verifier
   system — no parallel product model.

MVP scope: SubGoalUnit + RequiredOutput + depends_on + status + executor.
Fallback paths, error_history, complex verifier orchestration deferred to V2.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UnitStatus(str, Enum):
    PENDING = "pending"
    BLOCKED = "blocked"         # upstream dependency failed
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    DEGRADED = "degraded"       # completed with reduced scope (e.g. text instead of screenshot)


class OutputStatus(str, Enum):
    PENDING = "pending"
    PRODUCED = "produced"
    FAILED = "failed"
    SKIPPED = "skipped"         # non-required output skipped during degradation


class PlanStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# RequiredOutput — bound to artifact/verifier system
# ---------------------------------------------------------------------------

@dataclass
class RequiredOutput:
    """A concrete output that a SubGoalUnit must produce.

    Maps to the existing artifact/output_contract/verifier system:
    - output_type "file" → VerifierConditionType.FILE_EXISTS at verification
    - output_type "data" → ValueKind.JSON/TEXT at output_contract level
    - output_type "answer" → no file verification, text presence sufficient
    - mime_type_hint aligns with SkillOutputContract.mime_type
    """
    output_id: str
    output_type: str                        # "file" | "data" | "answer"
    description: str = ""                   # human-readable: "搜索结果页面的截图"
    format_hint: Optional[str] = None       # file extension: "png", "txt", "json"
    mime_type_hint: Optional[str] = None    # "image/png", "text/plain" — maps to output_contract
    required: bool = True                   # False = can be skipped during degradation
    status: OutputStatus = OutputStatus.PENDING
    actual_path: Optional[str] = None       # filled when produced
    artifact_id: Optional[str] = None       # filled when registered in ArtifactRegistry
    producing_node_id: Optional[str] = None # which graph node produced this
    inline_value: Optional[str] = None      # inlined text content for output_type="data"


# ---------------------------------------------------------------------------
# SkillHint — constraint, not script
# ---------------------------------------------------------------------------

@dataclass
class SkillHint:
    """Soft constraint for Planner skill selection.

    Expresses "preferred direction" and "prohibitions", NOT step-by-step
    skill sequences. The Planner retains full autonomy within these bounds.
    """
    preferred_skills: List[str] = field(default_factory=list)   # ["web.search", "llm.fallback"]
    prohibited_skills: List[str] = field(default_factory=list)  # ["browser.run"]
    reason: str = ""                                             # "搜索任务应走 web.search 而非浏览器自动化"


# ---------------------------------------------------------------------------
# SubGoalUnit
# ---------------------------------------------------------------------------

class UnitType(str, Enum):
    """Typed execution unit categories — constrains what skills and
    outputs are valid for a unit, preventing drift."""
    DESKTOP_CONTROL = "desktop_control"   # operate existing apps
    CODE_GENERATION = "code_generation"   # write/generate code files
    DATA_RETRIEVAL = "data_retrieval"     # search/fetch/read data
    FILE_PRODUCTION = "file_production"   # produce output files
    ANALYSIS = "analysis"                 # analyze data, produce insights
    CONFIGURATION = "configuration"       # configure/setup environment
    VERIFICATION = "verification"         # verify/test/validate
    GENERAL = "general"                   # unclassified


class DegradationPolicy(str, Enum):
    """What to do when a unit cannot fully satisfy its outputs."""
    FAIL = "fail"           # mark unit as failed
    DEGRADE = "degrade"     # mark as degraded, continue downstream
    SKIP = "skip"           # skip entirely, unblock downstream


@dataclass
class SubGoalUnit:
    """An independently executable sub-goal within a TaskExecutionPlan.

    The unit is the atomic scheduling entity. TaskPlanExecutor dispatches
    one unit at a time to GraphController (ReAct mode). The unit carries
    enough structured context that Planner doesn't need to guess what to
    produce or which skills to use.
    """
    unit_id: str
    objective: str                                  # concise goal text
    unit_type: UnitType = UnitType.GENERAL          # typed category
    required_outputs: List[RequiredOutput] = field(default_factory=list)
    skill_hint: Optional[SkillHint] = None
    allowed_skills: List[str] = field(default_factory=list)    # whitelist (empty = all allowed)
    forbidden_skills: List[str] = field(default_factory=list)  # blacklist
    depends_on: List[str] = field(default_factory=list)  # unit_ids this depends on
    input_refs: Dict[str, str] = field(default_factory=dict)
    # ^ {"search_results": "sg_0.output_search_data"} — references to upstream outputs
    degradation_policy: DegradationPolicy = DegradationPolicy.DEGRADE
    status: UnitStatus = UnitStatus.PENDING
    error_summary: Optional[str] = None             # brief failure reason (not raw JSON)
    retry_count: int = 0
    max_retries: int = 2


# ---------------------------------------------------------------------------
# TaskExecutionPlan — the state layer
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Helpers for upstream content injection
# ---------------------------------------------------------------------------

# Max chars to inline from an upstream output file into the downstream prompt.
# Large enough to be useful, small enough to stay within context budgets.
_RESOLVED_INPUT_PREVIEW_CHARS: int = 4000


def _read_file_preview(path: str, max_chars: int = _RESOLVED_INPUT_PREVIEW_CHARS) -> str:
    """Read a text file and return a truncated preview string.

    Returns empty string on any error (binary file, missing file, etc.).
    Binary files are skipped silently — only text content is inlined.
    """
    import os
    try:
        size = os.path.getsize(path)
        if size == 0:
            return ""
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            content = fh.read(max_chars)
        if not content.strip():
            return ""
        if len(content) == max_chars:
            content += "\n...[truncated]"
        return content
    except Exception:
        return ""


@dataclass
class TaskExecutionPlan:
    """Structured execution blueprint for complex tasks.

    This is the SINGLE SOURCE OF TRUTH for task execution state.
    GoalTracker and VerificationGate provide signals; this plan arbitrates.
    """
    plan_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    original_goal: str = ""
    units: List[SubGoalUnit] = field(default_factory=list)
    status: PlanStatus = PlanStatus.PENDING
    schema_version: str = "1.0.0"

    # ── Query methods ───────────────────────────────────────────────

    def get_next_unit(self) -> Optional[SubGoalUnit]:
        """Get the next executable unit (dependencies satisfied + pending).

        When an upstream unit is DEGRADED, check whether this unit's
        input_refs reference any FAILED outputs from that upstream.
        If so, block this unit — it cannot execute without the missing
        upstream output.
        """
        for unit in self.units:
            if unit.status != UnitStatus.PENDING:
                continue
            # Check all dependencies are completed or degraded
            deps_ok = True
            for dep_id in unit.depends_on:
                dep = self._get_unit(dep_id)
                if dep is None or dep.status not in (UnitStatus.COMPLETED, UnitStatus.DEGRADED):
                    deps_ok = False
                    break
                # If upstream is degraded, check if any of our input_refs
                # point to a FAILED output in that upstream unit.
                if dep.status == UnitStatus.DEGRADED and unit.input_refs:
                    for ref_value in unit.input_refs.values():
                        # input_refs format: "sg_X.output_id"
                        if not isinstance(ref_value, str) or "." not in ref_value:
                            continue
                        ref_unit_id, ref_output_id = ref_value.split(".", 1)
                        if ref_unit_id != dep_id:
                            continue
                        # Check if this specific output failed
                        for out in dep.required_outputs:
                            if out.output_id == ref_output_id and out.status == OutputStatus.FAILED:
                                unit.status = UnitStatus.BLOCKED
                                unit.error_summary = (
                                    f"blocked: upstream {dep_id} degraded, "
                                    f"required output {ref_output_id} not produced"
                                )
                                logger.info(
                                    "[TaskExecutionPlan] Unit %s blocked: "
                                    "input_ref %s references failed output "
                                    "%s.%s from degraded upstream",
                                    unit.unit_id, ref_value,
                                    dep_id, ref_output_id,
                                )
                                deps_ok = False
                                break
                        if not deps_ok:
                            break
                if not deps_ok:
                    break
            if deps_ok:
                return unit
        return None

    def get_unit(self, unit_id: str) -> Optional[SubGoalUnit]:
        """Public accessor for a unit by ID."""
        return self._get_unit(unit_id)

    def _get_unit(self, unit_id: str) -> Optional[SubGoalUnit]:
        for u in self.units:
            if u.unit_id == unit_id:
                return u
        return None

    # ── State mutation methods ──────────────────────────────────────

    def mark_unit_completed(
        self,
        unit_id: str,
        output_results: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        """Mark a unit as completed and update its output statuses.

        output_results: {output_id: {"path": str, "artifact_id": str, "node_id": str}}
        """
        unit = self._get_unit(unit_id)
        if unit is None:
            logger.warning("[TaskExecutionPlan] mark_completed: unknown unit %s", unit_id)
            return

        if output_results:
            for out in unit.required_outputs:
                if out.output_id in output_results:
                    info = output_results[out.output_id]
                    out.status = OutputStatus.PRODUCED
                    out.actual_path = info.get("path")
                    out.artifact_id = info.get("artifact_id")
                    out.producing_node_id = info.get("node_id")
                    # Store inlined text content for data-type outputs
                    # so downstream units can access it via build_unit_context.
                    if info.get("inline_value"):
                        out.inline_value = info["inline_value"]

        # Check if all required outputs are produced
        required_pending = [
            o for o in unit.required_outputs
            if o.required and o.status == OutputStatus.PENDING
        ]
        if required_pending:
            # Apply degradation policy
            if unit.degradation_policy == DegradationPolicy.FAIL:
                for o in required_pending:
                    o.status = OutputStatus.FAILED
                unit.status = UnitStatus.FAILED
                unit.error_summary = f"{len(required_pending)} required outputs missing (policy=fail)"
                self._propagate_failure(unit_id)
                logger.info(
                    "[TaskExecutionPlan] Unit %s FAILED (policy=fail): %d required outputs missing",
                    unit_id, len(required_pending),
                )
            elif unit.degradation_policy == DegradationPolicy.SKIP:
                for o in required_pending:
                    o.status = OutputStatus.SKIPPED
                unit.status = UnitStatus.DEGRADED
                logger.info(
                    "[TaskExecutionPlan] Unit %s degraded (policy=skip): %d outputs skipped",
                    unit_id, len(required_pending),
                )
            else:
                # Default: DEGRADE
                for o in required_pending:
                    o.status = OutputStatus.FAILED
                unit.status = UnitStatus.DEGRADED
                logger.info(
                    "[TaskExecutionPlan] Unit %s degraded: %d required outputs missing",
                    unit_id, len(required_pending),
                )
        else:
            unit.status = UnitStatus.COMPLETED

    def mark_unit_failed(self, unit_id: str, error_summary: str = "") -> None:
        """Mark a unit as failed and propagate to dependents."""
        unit = self._get_unit(unit_id)
        if unit is None:
            return
        unit.status = UnitStatus.FAILED
        unit.error_summary = error_summary
        for o in unit.required_outputs:
            if o.status == OutputStatus.PENDING:
                o.status = OutputStatus.FAILED
        self._propagate_failure(unit_id)

    def _propagate_failure(self, failed_unit_id: str) -> None:
        """Block all downstream units that depend on the failed unit."""
        for unit in self.units:
            if failed_unit_id in unit.depends_on and unit.status == UnitStatus.PENDING:
                unit.status = UnitStatus.BLOCKED
                logger.info(
                    "[TaskExecutionPlan] Unit %s blocked: dependency %s failed",
                    unit.unit_id, failed_unit_id,
                )
                # Recursive propagation
                self._propagate_failure(unit.unit_id)

    # ── Context building ────────────────────────────────────────────

    def build_unit_context(self, unit_id: str) -> Dict[str, Any]:
        """Build structured execution context for a unit.

        Returns a dict suitable for injection into env_context, containing:
        - resolved_inputs: {ref_name: actual_path} from upstream outputs
        - required_outputs: list of pending output specs
        - skill_hint: preferred/prohibited skills
        - error_context: brief failure info from previous attempts
        """
        unit = self._get_unit(unit_id)
        if unit is None:
            return {}

        # Resolve input references to actual paths + inline content preview
        resolved_inputs: Dict[str, str] = {}
        resolved_input_previews: Dict[str, str] = {}
        for ref_name, ref_spec in unit.input_refs.items():
            # ref_spec format: "sg_0.output_search_data"
            parts = ref_spec.split(".", 1)
            if len(parts) == 2:
                src_unit_id, src_output_id = parts
                src_unit = self._get_unit(src_unit_id)
                if src_unit:
                    for out in src_unit.required_outputs:
                        if out.output_id != src_output_id:
                            continue
                        if out.actual_path:
                            resolved_inputs[ref_name] = out.actual_path
                            # Try file preview first
                            preview = _read_file_preview(
                                out.actual_path,
                                max_chars=_RESOLVED_INPUT_PREVIEW_CHARS,
                            )
                            if preview:
                                resolved_input_previews[ref_name] = preview
                            elif out.inline_value:
                                # File unreadable but inline value available
                                resolved_input_previews[ref_name] = out.inline_value[:_RESOLVED_INPUT_PREVIEW_CHARS]
                        elif out.inline_value:
                            # output_type="data" — no file, use inlined text
                            resolved_inputs[ref_name] = "(inline)"
                            resolved_input_previews[ref_name] = out.inline_value[:_RESOLVED_INPUT_PREVIEW_CHARS]

        # Pending required outputs
        pending_outputs = [
            {
                "output_id": o.output_id,
                "type": o.output_type,
                "format": o.format_hint,
                "mime_type": o.mime_type_hint,
                "description": o.description,
            }
            for o in unit.required_outputs
            if o.status == OutputStatus.PENDING
        ]

        ctx: Dict[str, Any] = {
            "_plan_unit_id": unit.unit_id,
            "_unit_type": unit.unit_type.value,
            "_required_outputs": pending_outputs,
            "_resolved_inputs": resolved_inputs,
            "_resolved_input_previews": resolved_input_previews,
        }

        # Merge skill constraints: SkillHint + allowed/forbidden lists
        _preferred = list(unit.skill_hint.preferred_skills) if unit.skill_hint else []
        _prohibited = list(unit.skill_hint.prohibited_skills) if unit.skill_hint else []
        _reason = unit.skill_hint.reason if unit.skill_hint else ""

        if unit.allowed_skills:
            _preferred = list(set(_preferred + unit.allowed_skills))
        if unit.forbidden_skills:
            _prohibited = list(set(_prohibited + unit.forbidden_skills))

        if _preferred or _prohibited:
            ctx["_skill_hint"] = {
                "preferred": _preferred,
                "prohibited": _prohibited,
                "reason": _reason,
            }

        if unit.error_summary:
            ctx["_previous_error"] = unit.error_summary

        return ctx

    # ── Final status computation ────────────────────────────────────

    def compute_final_status(self) -> PlanStatus:
        """Compute overall plan status from unit statuses.

        This is the SINGLE ARBITER of task completion — GoalTracker and
        VerificationGate provide signals, but this method decides.
        """
        statuses = [u.status for u in self.units]

        if all(s == UnitStatus.COMPLETED for s in statuses):
            self.status = PlanStatus.COMPLETED
        elif all(s in (UnitStatus.FAILED, UnitStatus.BLOCKED) for s in statuses):
            self.status = PlanStatus.FAILED
        elif any(s in (UnitStatus.COMPLETED, UnitStatus.DEGRADED) for s in statuses):
            self.status = PlanStatus.PARTIAL_SUCCESS
        else:
            self.status = PlanStatus.FAILED

        return self.status

    # ── Serialization ───────────────────────────────────────────────

    def to_summary(self, max_chars: int = 500) -> str:
        """Human-readable summary for logging/narrative."""
        lines = [f"Plan {self.plan_id}: {self.status.value}"]
        for u in self.units:
            status_icon = {
                UnitStatus.COMPLETED: "✓",
                UnitStatus.DEGRADED: "◐",
                UnitStatus.FAILED: "✗",
                UnitStatus.BLOCKED: "⊘",
                UnitStatus.IN_PROGRESS: "→",
                UnitStatus.PENDING: "○",
            }.get(u.status, "?")
            lines.append(f"  {status_icon} {u.unit_id}: {u.objective[:60]}")
        result = "\n".join(lines)
        return result[:max_chars] if len(result) > max_chars else result
