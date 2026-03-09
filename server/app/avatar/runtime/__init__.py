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

# 监控日志
from .monitoring import StepLogger, TaskLog
from .monitoring.loggers import DatabaseStepLogger, InMemoryStepLogger

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
    # 监控
    "StepLogger",
    "TaskLog",
    "DatabaseStepLogger",
    "InMemoryStepLogger",
]
