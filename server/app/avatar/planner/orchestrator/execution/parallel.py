"""
并行执行策略 (Phase 2 - v0.4)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from .base import ExecutionStrategy

logger = logging.getLogger(__name__)


class ParallelExecutor(ExecutionStrategy):
    """
    并行执行策略
    
    特点：
    - 识别无依赖的子任务
    - 使用 asyncio.gather 并发执行
    - 限制最大并发数
    """
    
    def __init__(self, max_concurrent: int = 3):
        """
        Args:
            max_concurrent: 最大并发任务数
        """
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
    
    async def execute_subtasks(
        self,
        subtasks: List[Any],
        context: Dict[str, Any]
    ) -> None:
        """
        并行执行子任务
        
        Note:
            实际实现需要与 CompositeTaskExecutor 集成
            这里提供并发控制的框架
        """
        logger.info(
            f"Parallel execution: {len(subtasks)} subtasks "
            f"(max_concurrent={self._max_concurrent})"
        )
        
        # 实际执行逻辑需要在 TaskOrchestrator 中实现
        # 这里只是策略标识
    
    async def execute_with_limit(self, task_coro):
        """
        带并发限制的执行
        
        Args:
            task_coro: 任务协程
        """
        async with self._semaphore:
            return await task_coro

