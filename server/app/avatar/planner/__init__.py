# app/avatar/planner/__init__.py

"""
Avatar Planner 模块：任务规划和执行子系统

导出核心组件：
- Task, Step 等数据模型
- TaskPlanner（规划器：Intent → Task）
- Planner（执行器：Task → Skills）
- Registry（注册和查找 Planner）
"""

from .models import Task, Step, StepStatus, TaskStatus, StepResult
from .base import Planner, TaskPlanner, SkillContext, StateStore
from .registry import (
    register_planner,
    get_planner_class,
    create_planner,
    get_planner_for_intent,
    register_intent_mapping,
)
from .runners.dag_runner import DagRunner

# 导入 planners 模块以触发注册
from .planners import simple_llm  # noqa: F401

__all__ = [
    # 数据模型
    "Task",
    "Step",
    "StepStatus",
    "TaskStatus",
    "StepResult",
    # 基础协议
    "Planner",
    "TaskPlanner",
    "SkillContext",
    "StateStore",
    # 注册和查找
    "register_planner",
    "get_planner_class",
    "create_planner",
    "get_planner_for_intent",
    "register_intent_mapping",
    # 内置实现
    "DagRunner",
]
