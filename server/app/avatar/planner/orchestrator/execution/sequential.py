"""
顺序执行策略
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from .base import ExecutionStrategy

logger = logging.getLogger(__name__)


class SequentialStrategy(ExecutionStrategy):
    """
    顺序执行策略
    
    特点：
    - 按依赖顺序逐个执行子任务
    - 简单、可预测
    - 当前默认策略
    """
    
    async def execute_subtasks(
        self,
        subtasks: List[Any],
        context: Dict[str, Any]
    ) -> None:
        """
        顺序执行子任务
        
        Note:
            实际执行逻辑在 CompositeTaskExecutor 中
            这里主要是策略标识
        
        Args:
            subtasks: 子任务列表
            context: 执行上下文
        """
        logger.debug(f"Sequential execution strategy: {len(subtasks)} subtasks")
        # 实际执行由 CompositeTaskExecutor 完成

