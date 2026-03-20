"""
Task understanding layer — structured task definition, clarification,
runtime state, collaboration gates, and phased planning.

Re-exports all public types for convenient access.
"""

from .task_definition import (
    Assumption,
    Deliverable,
    FieldSource,
    Risk,
    SourcedTextItem,
    TaskDefinition,
    TaskDefinitionEngine,
)
from .clarification import (
    BlockingQuestion,
    ClarificationEngine,
    ExecutionReadiness,
    QuestionPriority,
)
from .runtime_state import (
    CompletedItem,
    CurrentBlocker,
    DecisionLogEntry,
    TaskRuntimeState,
    UpdateSource,
)
from .collaboration_gate import (
    CollaborationGate,
    GateRequest,
    GateType,
)
from .phased_planner import (
    GoalPlan,
    PhasePlan,
    PhasedPlanner,
    PhaseAcceptancePolicy,
    PhaseAcceptanceResult,
)

__all__ = [
    # task_definition.py
    "FieldSource",
    "SourcedTextItem",
    "Deliverable",
    "Assumption",
    "Risk",
    "TaskDefinition",
    "TaskDefinitionEngine",
    # clarification.py
    "QuestionPriority",
    "BlockingQuestion",
    "ExecutionReadiness",
    "ClarificationEngine",
    # runtime_state.py
    "UpdateSource",
    "CompletedItem",
    "CurrentBlocker",
    "DecisionLogEntry",
    "TaskRuntimeState",
    # collaboration_gate.py
    "GateType",
    "GateRequest",
    "CollaborationGate",
    # phased_planner.py
    "PhasePlan",
    "GoalPlan",
    "PhasedPlanner",
    "PhaseAcceptancePolicy",
    "PhaseAcceptanceResult",
]
