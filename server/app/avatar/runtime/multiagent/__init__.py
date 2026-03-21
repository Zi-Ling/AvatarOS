"""Multi-Agent Runtime — 多 Agent 协作运行时.

基于三层架构（Supervisor → GraphController → RuntimeKernel）的多 Agent 协作系统。
"""

from .role_spec import (
    RoleSpec,
    ContextScope,
    LifecyclePolicy,
    RoleSpecRegistry,
)
from .agent_instance import (
    AgentInstance,
    AgentInstanceState,
    AgentInstanceStatus,
    ResourceConsumption,
    RoleRunner,
    TaskPacket,
    SuccessCriterion,
)
from .handoff_envelope import HandoffEnvelope
from .subtask_graph import SubtaskGraph, SubtaskNode, SubtaskEdge
from .spawn_policy import SpawnPolicy
from .task_ownership import TaskOwnershipManager, OwnershipRecord, OwnershipConflictError
from .artifact import Artifact as MultiAgentArtifact, ArtifactStore
from .supervisor import (
    Supervisor,
    ComplexityEvaluator,
    ComplexityAssessment,
    InstanceManager,
    GraphValidator,
    TerminationEvaluator,
)
from .trace_integration import TraceIntegration

__all__ = [
    "RoleSpec", "ContextScope", "LifecyclePolicy", "RoleSpecRegistry",
    "AgentInstance", "AgentInstanceState", "AgentInstanceStatus",
    "ResourceConsumption", "RoleRunner", "TaskPacket", "SuccessCriterion",
    "HandoffEnvelope",
    "SubtaskGraph", "SubtaskNode", "SubtaskEdge",
    "SpawnPolicy",
    "TaskOwnershipManager", "OwnershipRecord", "OwnershipConflictError",
    "MultiAgentArtifact", "ArtifactStore",
    "Supervisor", "ComplexityEvaluator", "ComplexityAssessment",
    "InstanceManager", "GraphValidator", "TerminationEvaluator",
    "TraceIntegration",
]
