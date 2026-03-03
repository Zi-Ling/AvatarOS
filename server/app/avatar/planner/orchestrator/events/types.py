"""
编排器专用事件类型
"""
from __future__ import annotations

from enum import Enum


class CompositeTaskEventType(str, Enum):
    """复合任务事件类型"""
    
    # 思考阶段
    TASK_THINKING = "task_thinking"
    
    # 分解阶段
    TASK_DECOMPOSED = "task_decomposed"
    
    # 子任务执行
    SUBTASK_START = "subtask_start"
    SUBTASK_COMPLETE = "subtask_complete"
    SUBTASK_FAILED = "subtask_failed"
    
    # 整体任务完成
    COMPOSITE_TASK_COMPLETE = "composite_task_complete"
    COMPOSITE_TASK_PROGRESS = "composite_task_progress"

