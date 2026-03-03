# app/avatar/runtime/recovery/__init__.py
"""
错误恢复模块
"""
from .repair import (
    CodeRepairManager,
    RepairResult,
    RepairValidator,
    ValidationResult,
    PatchApplier,
    SelfCorrector,
)
from .retry import (
    RetryConfig,
    retry_with_backoff,
    async_retry_with_backoff,
    RetryableError,
    NonRetryableError,
)
from .replanner import Replanner

__all__ = [
    # Repair
    "CodeRepairManager",
    "RepairResult",
    "RepairValidator",
    "ValidationResult",
    "PatchApplier",
    "SelfCorrector",
    # Retry
    "RetryConfig",
    "retry_with_backoff",
    "async_retry_with_backoff",
    "RetryableError",
    "NonRetryableError",
    # Replanner
    "Replanner",
]
