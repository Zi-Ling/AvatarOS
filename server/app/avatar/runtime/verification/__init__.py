# app/avatar/runtime/verification
# Task completion verification subsystem

from app.avatar.runtime.verification.models import (
    RiskLevel,
    ExpectedArtifact,
    NormalizedGoal,
    VerificationTarget,
    VerificationStatus,
    VerificationResult,
    GateVerdict,
    GateDecision,
    TaskTerminalState,
    VerifierConditionType,
    VerifierSpec,
    SubGoalStatus,
    GoalCoverageSummary,
    RepairFeedback,
)
from app.avatar.runtime.verification.goal_normalizer import GoalNormalizer
from app.avatar.runtime.verification.target_resolver import TargetResolver
from app.avatar.runtime.verification.verifier_registry import VerifierRegistry, DomainVerifierPack
from app.avatar.runtime.verification.completion_gate import CompletionGate
from app.avatar.runtime.verification.goal_coverage_tracker import GoalCoverageTracker
from app.avatar.runtime.verification.repair_loop import RepairLoop
from app.avatar.runtime.verification.finish_bias_check import FinishBiasCheck

__all__ = [
    "RiskLevel", "ExpectedArtifact", "NormalizedGoal", "VerificationTarget",
    "VerificationStatus", "VerificationResult", "GateVerdict", "GateDecision",
    "TaskTerminalState", "VerifierConditionType", "VerifierSpec",
    "SubGoalStatus", "GoalCoverageSummary", "RepairFeedback",
    "GoalNormalizer", "TargetResolver", "VerifierRegistry", "DomainVerifierPack",
    "CompletionGate", "GoalCoverageTracker", "RepairLoop", "FinishBiasCheck",
]
