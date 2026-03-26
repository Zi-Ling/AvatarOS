"""Multi-Agent Runtime — 多 Agent 协作运行时.

基于三层架构（Supervisor → GraphController → RuntimeKernel）的多 Agent 协作系统。
"""

from .roles.role_spec import (
    RoleSpec,
    ContextScope,
    LifecyclePolicy,
    RoleSpecRegistry,
)
from .roles.agent_instance import (
    AgentInstance,
    AgentInstanceState,
    AgentInstanceStatus,
    ResourceConsumption,
    RoleRunner,
    TaskPacket,
    SuccessCriterion,
)
from .core.handoff_envelope import HandoffEnvelope
from .core.subtask_graph import SubtaskGraph, SubtaskNode, SubtaskEdge
from .roles.spawn_policy import SpawnPolicy
from .execution.task_ownership import TaskOwnershipManager, OwnershipRecord, OwnershipConflictError
from .persistence.artifact import Artifact as MultiAgentArtifact, ArtifactStore
from .core.supervisor import (
    Supervisor,
    ComplexityEvaluator,
    ComplexityAssessment,
    InstanceManager,
    GraphValidator,
    TerminationEvaluator,
)
from .observability.trace_integration import TraceIntegration
from .config import MultiAgentConfig
from .roles.role_runners import (
    BaseRoleRunner,
    ResearcherRunner,
    ExecutorRunner,
    WriterRunner,
    ReviewerRunner,
    get_role_runner,
)
from .core.supervisor_runtime import (
    SupervisorRuntime,
    WorkerInstance,
    TaskResult,
    RuntimeResult,
)
from .resilience.health_monitor import AgentHealthMonitor, HealthStatus, WorkerHealth
from .resilience.repair_loop import RepairLoop, RepairAction, RepairDecision
from .execution.worker_pool import WorkerPoolManager, PoolAction, PoolEvent
from .resilience.decision_advisor import (
    DecisionAdvisor, RuleOnlyAdvisor, LLMDecisionAdvisor,
    Advisory, AdvisoryAction, AdvisorContext,
)
from .core.supervisor_agent import (
    SupervisorAgent, SupervisorAction, SupervisorDecision,
)

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
    "MultiAgentConfig",
    "BaseRoleRunner", "ResearcherRunner", "ExecutorRunner", "WriterRunner",
    "ReviewerRunner", "get_role_runner",
    "SupervisorRuntime", "WorkerInstance", "TaskResult", "RuntimeResult",
    "AgentHealthMonitor", "HealthStatus", "WorkerHealth",
    "RepairLoop", "RepairAction", "RepairDecision",
    "WorkerPoolManager", "PoolAction", "PoolEvent",
    "DecisionAdvisor", "RuleOnlyAdvisor", "LLMDecisionAdvisor",
    "Advisory", "AdvisoryAction", "AdvisorContext",
    "SupervisorAgent", "SupervisorAction", "SupervisorDecision",
]
