# app/avatar/runtime/recovery/repair/__init__.py
"""
代码自我修复模块（新架构：RepairSnapshot 已废弃，改用 TaskContext.status.repair_state）
"""
from .manager import CodeRepairManager, RepairResult
from .validator import RepairValidator, ValidationResult
from .patch import PatchApplier
from .corrector import SelfCorrector

__all__ = [
    "CodeRepairManager",
    "RepairResult",
    "RepairValidator",
    "ValidationResult",
    "PatchApplier",
    "SelfCorrector",
]
