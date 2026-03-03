"""
Plan Optimizer Module

计划优化模块，提供各种计划优化策略。
"""

from .plan_optimizer import PlanOptimizer, get_plan_optimizer, optimize_task
from .deduplicator import SubTaskDeduplicator
from .dependency_validator import DependencyValidator

# 向后兼容
SubTaskOptimizer = PlanOptimizer

__all__ = [
    "PlanOptimizer",
    "get_plan_optimizer",
    "optimize_task",
    "SubTaskDeduplicator",
    "DependencyValidator",
    "SubTaskOptimizer",  # 向后兼容
]
