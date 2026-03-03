"""
Stage Executor Base Class

Defines the interface for stage execution.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

from ..template import WorkflowStage


class StageExecutor(ABC):
    """
    阶段执行器抽象基类
    
    定义阶段执行的统一接口
    """
    
    @abstractmethod
    async def execute(
        self,
        stage: WorkflowStage,
        inputs: Dict[str, Any],
        env_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        执行阶段
        
        Args:
            stage: 工作流阶段
            inputs: 输入数据
            env_context: 环境上下文
            
        Returns:
            输出数据
        """
        pass

