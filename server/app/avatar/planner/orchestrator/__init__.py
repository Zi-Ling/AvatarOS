"""
编排服务模块

职责：
- 任务分解
- Intent 构造
- 依赖解析
- 输出收集

这是编排层的核心，所有编排相关的操作都通过 OrchestrationService。
"""
from .service import OrchestrationService
from .intent_factory import IntentFactory
from .dependency_resolver import DependencyResolver
from .output_collector import OutputCollector
from .execution.policies import FailurePolicy, SuccessPolicy

__all__ = [
    "OrchestrationService",
    "IntentFactory",
    "DependencyResolver",
    "OutputCollector",
    "FailurePolicy",
    "SuccessPolicy",
]

