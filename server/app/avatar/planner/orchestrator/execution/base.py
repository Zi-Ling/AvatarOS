"""
执行策略抽象基类
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from ...planner.models import SubTask


class ExecutionStrategy(ABC):
    """
    执行策略抽象基类
    
    定义如何执行子任务（顺序、并行等）
    """
    
    @abstractmethod
    async def execute_subtasks(
        self,
        subtasks: List[SubTask],
        context: Dict[str, Any]
    ) -> None:
        """
        执行子任务列表
        
        Args:
            subtasks: 要执行的子任务列表
            context: 执行上下文
        """
        raise NotImplementedError

