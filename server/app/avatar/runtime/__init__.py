# app/avatar/runtime/__init__.py
"""
Avatar Runtime - 智能体运行时
"""

# 核心抽象（最常用）
from .core import (
    TaskContext,
    StepContext,
    ExecutionContext,
    SessionContext,
    AgentLoopResult,
    ErrorClassifier,
)

# 主入口
from .main import AvatarMain
from .loop import AgentLoop

# 监控日志
from .monitoring import StepLogger, TaskLog
from .monitoring.loggers import DatabaseStepLogger, InMemoryStepLogger

# 错误恢复
from .recovery import CodeRepairManager, Replanner
from .recovery.repair import SelfCorrector

# 缓存
from .cache import (
    PlanCache,
    PlanTemplate,
    PlanValidator,
    CacheKeyGenerator,
    CacheRejectReason,
    StepSkeleton,
    QualityMetrics,
    get_plan_cache,
)

__all__ = [
    # 核心
    "TaskContext",
    "StepContext",
    "ExecutionContext",
    "SessionContext",
    "AgentLoopResult",
    "ErrorClassifier",
    # 主入口
    "AvatarMain",
    "AgentLoop",
    # 监控
    "StepLogger",
    "TaskLog",
    "DatabaseStepLogger",
    "InMemoryStepLogger",
    # 恢复
    "CodeRepairManager",
    "Replanner",
    "SelfCorrector",
    # 缓存
    "PlanCache",
    "PlanTemplate",
    "PlanValidator",
    "CacheKeyGenerator",
    "CacheRejectReason",
    "StepSkeleton",
    "QualityMetrics",
    "get_plan_cache",
]
