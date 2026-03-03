# app/avatar/runtime/core/__init__.py
"""
核心抽象层
"""
from .base_executor import ExecutorProtocol, BaseExecutor
from .result import AgentLoopResult, StepExecutionResult
from .context import TaskContext, StepContext, ExecutionContext
from .errors import ErrorClassifier, ErrorInfo, ErrorType, ErrorSeverity
from .session import SessionContext

__all__ = [
    # 执行器
    "ExecutorProtocol",
    "BaseExecutor",
    "AgentLoopResult",
    "StepExecutionResult",
    # 上下文
    "TaskContext",
    "StepContext",
    "ExecutionContext",
    # 错误处理
    "ErrorClassifier",
    "ErrorInfo",
    "ErrorType",
    "ErrorSeverity",
    # 会话
    "SessionContext",
]

