"""
Checkpoint 数据模型
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List


@dataclass
class TaskCheckpoint:
    """
    任务检查点
    
    保存任务执行的中间状态，用于断点续跑
    """
    
    checkpoint_id: str
    task_id: str
    composite_task_data: Dict[str, Any]  # CompositeTask 序列化数据
    current_subtask_index: int           # 当前执行到第几个子任务
    completed_subtask_ids: List[str]     # 已完成的子任务ID列表
    outputs_cache: Dict[str, Any]        # 中间产物缓存
    plan_version: int = 1                # Plan 版本号
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

