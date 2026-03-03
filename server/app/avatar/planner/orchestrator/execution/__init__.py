"""
执行策略模块
"""
from .base import ExecutionStrategy
from .sequential import SequentialStrategy

__all__ = ["ExecutionStrategy", "SequentialStrategy"]

