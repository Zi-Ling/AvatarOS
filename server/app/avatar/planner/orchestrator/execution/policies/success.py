"""
成功判定策略
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from ....models.subtask import SubTask, SubTaskStatus


@dataclass
class SuccessPolicy:
    """
    成功判定策略
    
    Attributes:
        success_threshold: 成功率阈值（0.0-1.0），用于判定 partial_success
    """
    
    success_threshold: float = 0.5  # 默认50%成功率
    
    def evaluate_status(self, subtasks: List[SubTask]) -> str:
        """
        评估整体任务状态
        
        Args:
            subtasks: 子任务列表
        
        Returns:
            str: "success" | "partial_success" | "failed"
        """
        total = len(subtasks)
        if total == 0:
            return "success"
        
        success_count = sum(
            1 for st in subtasks
            if st.status == SubTaskStatus.SUCCESS
        )
        failed_count = sum(
            1 for st in subtasks
            if st.status == SubTaskStatus.FAILED
        )
        skipped_count = sum(
            1 for st in subtasks
            if st.status == SubTaskStatus.SKIPPED
        )
        
        # 全部成功或跳过
        if success_count + skipped_count == total and success_count > 0:
            return "success"
        
        # 计算成功率
        success_rate = success_count / total
        
        # 没有成功的，或成功率低于阈值
        if success_count == 0 or success_rate < self.success_threshold:
            return "failed"
        
        # 部分成功
        return "partial_success"

