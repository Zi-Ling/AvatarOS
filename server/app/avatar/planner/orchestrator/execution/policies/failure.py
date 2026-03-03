"""
失败处理策略
"""
from __future__ import annotations

from enum import Enum
from dataclasses import dataclass


class FailureStrategy(str, Enum):
    """失败处理策略枚举"""
    
    FAIL_FAST = "fail_fast"  # 快速失败：一个失败就停止
    CONTINUE = "continue"    # 继续执行：失败后继续执行其他任务
    PARTIAL = "partial"      # 部分成功：允许部分子任务失败


@dataclass
class FailurePolicy:
    """
    失败处理策略配置
    
    Attributes:
        strategy: 失败策略
        max_failures: 最大允许失败数（仅对 PARTIAL 策略有效）
        critical_subtask_ids: 关键子任务ID列表（这些任务失败必须停止）
    """
    
    strategy: FailureStrategy = FailureStrategy.CONTINUE
    max_failures: int = 1  # 最多允许1个失败
    critical_subtask_ids: list = None
    
    def __post_init__(self):
        if self.critical_subtask_ids is None:
            self.critical_subtask_ids = []
    
    def should_stop_on_failure(
        self,
        failed_subtask_id: str,
        total_failures: int
    ) -> bool:
        """
        判断是否应该因失败而停止执行
        
        Args:
            failed_subtask_id: 失败的子任务ID
            total_failures: 当前总失败数
        
        Returns:
            bool: True 表示应该停止
        """
        # 如果是关键子任务失败，必须停止
        if failed_subtask_id in self.critical_subtask_ids:
            return True
        
        # 根据策略判断
        if self.strategy == FailureStrategy.FAIL_FAST:
            return True
        
        if self.strategy == FailureStrategy.CONTINUE:
            return False
        
        if self.strategy == FailureStrategy.PARTIAL:
            return total_failures >= self.max_failures
        
        return False

