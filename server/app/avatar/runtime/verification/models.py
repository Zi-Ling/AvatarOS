"""
Verification data models for task completion verification.

All core data structures used across the verification subsystem.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional


# ---------------------------------------------------------------------------
# Risk & Goal models
# ---------------------------------------------------------------------------

class RiskLevel(str, Enum):
    LOW = "low"       # read-only queries, plain text summaries
    MEDIUM = "medium" # file writes, data processing
    HIGH = "high"     # network requests, system commands, bulk modifications, email


@dataclass
class ExpectedArtifact:
    label: str                        # semantic label, e.g. "output_image"
    mime_type: Optional[str] = None   # expected MIME type, e.g. "image/png"
    path_hint: Optional[str] = None   # path hint, e.g. "output/*.csv"
    required: bool = True


@dataclass
class DeliverableSpec:
    """Static definition of a single deliverable (file/artifact) expected by the goal."""
    id: str                                     # e.g. "d1", "d2"
    format: str                                 # file extension without dot: "md", "txt", "json", ...
    path_hint: Optional[str] = None             # e.g. "output/content.md"
    semantic_role: Optional[str] = None         # e.g. "report", "summary", "export"
    source_ref: Optional[str] = None            # which part of the goal this came from
    required: bool = True


@dataclass
class DeliverableState:
    """Runtime tracking state for a single deliverable (separate from static spec)."""
    deliverable_id: str                         # matches DeliverableSpec.id
    status: str = "pending"                     # "pending" | "satisfied" | "failed"
    matched_path: Optional[str] = None          # actual file path produced
    producing_step_id: Optional[str] = None     # node id that produced this
    verification_passed: bool = False           # True only after verifier confirms
    evidence: Optional[str] = None


@dataclass
class NormalizedGoal:
    original: str
    goal_type: str                              # "file_transform" | "report_gen" | "data_analysis" | ...
    expected_artifacts: List[ExpectedArtifact]
    verification_intents: List[str]             # e.g. ["file_exists", "image_openable"]
    risk_level: RiskLevel
    requires_human_approval: bool = False
    sub_goals: List[str] = field(default_factory=list)
    matched_domain_pack: Optional[str] = None  # P3: DomainPack.pack_id if matched
    deliverables: List[DeliverableSpec] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Verification target
# ---------------------------------------------------------------------------

@dataclass
class VerificationTarget:
    kind: Literal["file", "url", "artifact_ref", "directory"]
    path: Optional[str] = None
    url: Optional[str] = None
    artifact_ref: Optional[str] = None
    mime_type: Optional[str] = None
    producer_step_id: Optional[str] = None   # step that produced this target
    metadata: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Verification result
# ---------------------------------------------------------------------------

class VerificationStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    SKIPPED = "skipped"


_EVIDENCE_MAX_BYTES = 4096  # 4 KB hard cap


@dataclass
class VerificationResult:
    verifier_name: str
    target: VerificationTarget
    status: VerificationStatus
    reason: str
    evidence: Optional[Dict[str, Any]] = None
    evidence_artifact_ref: Optional[str] = None   # ref when evidence exceeds 4 KB
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    cost: float = 0.0
    repair_hint: Optional[str] = None
    is_blocking: bool = True

    def to_trace_payload(self) -> Dict[str, Any]:
        """Serialize to StepTraceStore.record_event payload. Truncates evidence > 4 KB."""
        evidence = self.evidence
        evidence_artifact_ref = self.evidence_artifact_ref

        if evidence is not None:
            serialized = json.dumps(evidence, default=str, ensure_ascii=False).encode("utf-8")
            if len(serialized) > _EVIDENCE_MAX_BYTES:
                evidence = {"_truncated": True, "size_bytes": len(serialized)}
                # evidence_artifact_ref should be set by caller if full evidence is stored

        return {
            "verifier_name": self.verifier_name,
            "target_kind": self.target.kind,
            "target_path": self.target.path,
            "target_producer_step_id": self.target.producer_step_id,
            "status": self.status.value,
            "is_blocking": self.is_blocking,
            "reason": self.reason,
            "evidence": evidence,
            "evidence_artifact_ref": evidence_artifact_ref,
            "cost": self.cost,
            "repair_hint": self.repair_hint,
        }


# ---------------------------------------------------------------------------
# Gate verdict & decision
# ---------------------------------------------------------------------------

class GateVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNCERTAIN = "UNCERTAIN"


@dataclass
class GateDecision:
    verdict: GateVerdict
    passed_count: int = 0
    failed_count: int = 0
    uncertain_count: int = 0
    failed_results: List[VerificationResult] = field(default_factory=list)
    uncertain_results: List[VerificationResult] = field(default_factory=list)
    reason: str = ""
    trace_hole: bool = False          # set True when trace write fails
    llm_judge_prompt: Optional[str] = None


# ---------------------------------------------------------------------------
# Task terminal state
# ---------------------------------------------------------------------------

class TaskTerminalState(str, Enum):
    COMPLETED = "completed"                    # all blocking verifiers PASS, coverage satisfied
    PARTIAL_SUCCESS = "partial_success"        # some sub-goals done, repair exhausted
    FAILED = "failed"                          # blocking verifier FAIL, unrecoverable
    UNCERTAIN_TERMINAL = "uncertain_terminal"  # LLM Judge unavailable, HIGH risk, needs human


# ---------------------------------------------------------------------------
# Verifier spec
# ---------------------------------------------------------------------------

class VerifierConditionType(str, Enum):
    FILE_EXISTS = "file_exists"
    JSON_PARSEABLE = "json_parseable"
    IMAGE_OPENABLE = "image_openable"
    CSV_HAS_DATA = "csv_has_data"
    TEXT_CONTAINS = "text_contains"
    JSON_SCHEMA = "json_schema"
    CSV_COLUMNS = "csv_columns"
    REPORT_DELIVERABLE = "report_deliverable"
    CUSTOM = "custom"


@dataclass
class VerifierSpec:
    name: str
    condition_type: VerifierConditionType
    description: str
    priority: int = 0
    blocking: bool = True                                        # True = FAIL on failure
    severity: Literal["critical", "normal", "advisory"] = "normal"
    weight: float = 1.0                                          # for UNCERTAIN weight calc
    allowed_paths: List[str] = field(default_factory=list)       # declarative whitelist


# ---------------------------------------------------------------------------
# Goal coverage
# ---------------------------------------------------------------------------

@dataclass
class SubGoalStatus:
    description: str
    ever_satisfied: bool = False       # monotonically non-decreasing (audit)
    currently_satisfied: bool = False  # can revert (used for PASS decision)
    evidence: Optional[str] = None
    verifier_result: Optional[VerificationResult] = None


@dataclass
class GoalCoverageSummary:
    goal: str
    sub_goals: List[SubGoalStatus] = field(default_factory=list)
    satisfied_count: int = 0
    total_count: int = 0
    coverage_ratio: float = 0.0
    last_updated_at: Optional[float] = None
    deliverable_satisfied_count: int = 0
    deliverable_total_count: int = 0

    @property
    def is_currently_covered(self) -> bool:
        """True only when ALL sub_goals are currently_satisfied."""
        return self.total_count > 0 and all(sg.currently_satisfied for sg in self.sub_goals)

    @property
    def is_ever_covered(self) -> bool:
        """Historical coverage — for audit only."""
        return self.total_count > 0 and all(sg.ever_satisfied for sg in self.sub_goals)

    def to_planner_hint(self, max_chars: int = 500) -> str:
        """
        Short planner hint injected into env_context.
        Only references step_id / artifact label / brief failure reason.
        Hard-truncated to max_chars to prevent context bloat.
        """
        if not self.sub_goals:
            return f"[coverage] goal='{self.goal[:80]}' no sub-goals tracked"

        lines = [f"[coverage] {self.satisfied_count}/{self.total_count} sub-goals satisfied"]
        if self.deliverable_total_count > 0:
            lines[0] += f", {self.deliverable_satisfied_count}/{self.deliverable_total_count} deliverables"
        for sg in self.sub_goals:
            status = "✓" if sg.currently_satisfied else "✗"
            ev = f" ({sg.evidence})" if sg.evidence else ""
            lines.append(f"  {status} {sg.description[:60]}{ev}")

        hint = "\n".join(lines)
        if len(hint) > max_chars:
            hint = hint[:max_chars - 3] + "..."
        return hint


# ---------------------------------------------------------------------------
# Repair feedback
# ---------------------------------------------------------------------------

class FailureCategory(str, Enum):
    """Structured failure category for repair attribution."""
    FILE_NOT_FOUND = "file_not_found"
    FORMAT_ERROR = "format_error"
    CONTENT_INVALID = "content_invalid"
    PERMISSION_DENIED = "permission_denied"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


@dataclass
class StructuredFailureAttribution:
    """Structured failure attribution — core of RepairFeedback."""
    failed_verifier_name: str
    failure_category: FailureCategory
    repair_hint: str
    target_path: Optional[str] = None
    producer_step_id: Optional[str] = None   # from ArtifactRegistry.get(id).producer_step
    strategy_exhausted: bool = False          # allow Planner to try other paths


@dataclass
class RepairFeedback:
    failed_verifications: List[VerificationResult]
    repair_hints: List[str]
    suggested_strategy: str   # "rerun_last_step" | "patch_file" | "full_retry"
    attributions: List[StructuredFailureAttribution] = field(default_factory=list)
    affected_step_ids: List[str] = field(default_factory=list)
    producer_step_ids: List[str] = field(default_factory=list)
    context_patch: Dict[str, Any] = field(default_factory=dict)

    def to_planner_summary(self) -> str:
        """
        Format as a "上一轮失败原因" paragraph for PlannerPromptBuilder.
        References step / artifact / verifier explicitly.
        Does NOT pass raw error strings.
        """
        if not self.attributions:
            # Fallback: use repair_hints
            lines = ["上一轮失败原因："]
            for hint in self.repair_hints[:5]:
                lines.append(f"  - {hint}")
            return "\n".join(lines)

        lines = ["上一轮失败原因："]
        for attr in self.attributions:
            step_info = f"，建议修复步骤：{attr.producer_step_id}" if attr.producer_step_id else ""
            path_info = f" 在 {attr.target_path}" if attr.target_path else ""
            exhausted_info = "（策略已耗尽，可转向其他路径）" if attr.strategy_exhausted else ""
            lines.append(
                f"  - [{attr.failed_verifier_name}]{path_info} 失败：{attr.repair_hint}"
                f"（失败类型：{attr.failure_category.value}）{step_info}{exhausted_info}"
            )
        if self.suggested_strategy:
            lines.append(f"  建议修复策略：{self.suggested_strategy}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# P3: TerminalState — formal terminal state enumeration
# ---------------------------------------------------------------------------

class TerminalState(str, Enum):
    """
    Formal terminal states for task execution.
    Once a task enters a TerminalState, no further state transitions are allowed.
    """
    COMPLETED = "completed"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    WAITING_APPROVAL = "waiting_approval"
    BLOCKED_BY_APPROVAL = "blocked_by_approval"
    APPROVAL_REJECTED = "approval_rejected"
    REPAIR_EXHAUSTED = "repair_exhausted"


class InvalidStateTransitionError(Exception):
    """Raised when attempting to transition from a terminal state."""
    def __init__(self, current_state: TerminalState, attempted_state: str):
        super().__init__(
            f"Cannot transition from terminal state '{current_state.value}' to '{attempted_state}'"
        )
        self.current_state = current_state
        self.attempted_state = attempted_state
