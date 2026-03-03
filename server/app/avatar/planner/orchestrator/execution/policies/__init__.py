"""
执行策略配置
"""
from .failure import FailurePolicy, FailureStrategy
from .success import SuccessPolicy

__all__ = ["FailurePolicy", "FailureStrategy", "SuccessPolicy"]

