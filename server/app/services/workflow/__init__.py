"""
工作流编排系统（Workflow Orchestration）。

核心模块：
- models: 数据模型（枚举、Pydantic、SQLModel）
- template_store: 模板 CRUD + 版本管理
- param_resolver: 参数占位符替换
- condition_evaluator: 条件表达式求值
- dag_scheduler: DAG 拓扑排序 + 依赖推进
- step_executor: 步骤执行抽象
- instance_manager: 实例生命周期管理
- trigger_manager: 触发器管理
"""
from app.services.workflow.models import (
    ConditionExpr,
    InstanceStatus,
    StepExecutorType,
    StepFailurePolicy,
    StepRunStatus,
    TriggerType,
    VersionMode,
    WorkflowEdgeDef,
    WorkflowInstance,
    WorkflowParamDef,
    WorkflowStepDef,
    WorkflowStepRun,
    WorkflowTemplate,
    WorkflowTemplateVersion,
    WorkflowTrigger,
)
from app.services.workflow.template_store import TemplateStore
from app.services.workflow.param_resolver import ParamResolver
from app.services.workflow.condition_evaluator import ConditionEvaluator
from app.services.workflow.dag_scheduler import WorkflowDAGScheduler
from app.services.workflow.step_executor import (
    OutputContractValidator,
    SkillStepExecutor,
    StepExecutor,
    StepRunResult,
    TaskSessionStepExecutor,
)
from app.services.workflow.instance_manager import InstanceManager
from app.services.workflow.trigger_manager import TriggerManager

__all__ = [
    "TemplateStore",
    "ParamResolver",
    "ConditionEvaluator",
    "WorkflowDAGScheduler",
    "StepExecutor",
    "OutputContractValidator",
    "SkillStepExecutor",
    "TaskSessionStepExecutor",
    "StepRunResult",
    "InstanceManager",
    "TriggerManager",
]
