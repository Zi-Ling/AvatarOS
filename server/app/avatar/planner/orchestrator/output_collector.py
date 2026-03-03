"""
输出收集器（OutputCollector）

职责：
- 调用 OutputExtractor 提取原始输出
- 映射到 subtask.expected_outputs
- 更新 subtask.actual_outputs

这是编排层的输出管理，比 OutputExtractor 更高层。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from ..models.subtask import CompositeTask, SubTask
from ..models import Task
from .output.extractor import OutputExtractor

logger = logging.getLogger(__name__)


class OutputCollector:
    """
    输出收集器（编排层的输出管理）
    
    封装 OutputExtractor，提供更高层的输出收集接口。
    """
    
    def __init__(self, output_extractor: OutputExtractor):
        """
        初始化输出收集器
        
        Args:
            output_extractor: OutputExtractor 实例
        """
        self._extractor = output_extractor
    
    def collect(
        self,
        subtask: SubTask,
        task: Task,
        composite: CompositeTask
    ) -> Dict[str, Any]:
        """
        收集子任务输出
        
        步骤：
        1. 调用 OutputExtractor 提取原始输出
        2. 更新 subtask.actual_outputs
        3. 返回提取的输出
        
        Args:
            subtask: 当前子任务
            task: 执行完成的 Task
            composite: 所属的复合任务
        
        Returns:
            Dict[str, Any]: 提取的输出字典
        """
        logger.debug(
            f"[OutputCollector] Collecting outputs for {subtask.id}, "
            f"expected={subtask.expected_outputs}"
        )
        
        # 1. 提取原始输出（传递 subtask_type 以提取标准字段）
        outputs = self._extractor.extract_task_outputs(
            task=task,
            expected_outputs=subtask.expected_outputs,
            subtask_type=subtask.type  # 【关键】传递类型
        )
        
        # 2. 更新 subtask.actual_outputs
        subtask.actual_outputs.update(outputs)
        
        # 3. 记录日志
        logger.info(
            f"[OutputCollector] Collected outputs for {subtask.id}: "
            f"{list(outputs.keys())}"
        )
        
        return outputs

