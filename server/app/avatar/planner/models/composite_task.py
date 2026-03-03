# app/avatar/planner/models/composite_task.py
"""
复合任务模型：支持将复杂请求分解为多个子任务
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
import uuid


class SubTaskStatus(str, Enum):
    """子任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class SubTask:
    """
    子任务：一个独立的可执行目标
    每个子任务会被转换为一个 Task（包含多个 Steps）
    """
    id: str
    goal: str  # 子任务目标描述
    order: int  # 执行顺序
    inputs: Dict[str, Any] = field(default_factory=dict)  # 输入参数
    outputs: Dict[str, Any] = field(default_factory=dict)  # 输出结果
    depends_on: List[str] = field(default_factory=list)  # 依赖的子任务ID
    status: SubTaskStatus = SubTaskStatus.PENDING
    error: Optional[str] = None
    task_result: Optional[Any] = None  # 执行后的 Task 对象
    
    @staticmethod
    def create(goal: str, order: int = 0, **kwargs) -> SubTask:
        """工厂方法"""
        return SubTask(
            id=f"subtask_{uuid.uuid4().hex[:8]}",
            goal=goal,
            order=order,
            **kwargs
        )


@dataclass
class CompositeTask:
    """
    复合任务：包含多个子任务的编排结构
    """
    id: str
    original_request: str  # 用户原始请求
    subtasks: List[SubTask] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @staticmethod
    def create(original_request: str) -> CompositeTask:
        """工厂方法"""
        return CompositeTask(
            id=f"composite_{uuid.uuid4().hex[:8]}",
            original_request=original_request
        )
    
    def add_subtask(self, subtask: SubTask) -> None:
        """添加子任务"""
        self.subtasks.append(subtask)
    
    def get_ready_subtasks(self) -> List[SubTask]:
        """
        获取所有依赖已满足的待执行子任务
        """
        ready = []
        for subtask in self.subtasks:
            if subtask.status != SubTaskStatus.PENDING:
                continue
            
            # 检查依赖
            can_run = True
            for dep_id in subtask.depends_on:
                dep = self.get_subtask_by_id(dep_id)
                if not dep or dep.status != SubTaskStatus.SUCCESS:
                    can_run = False
                    break
            
            if can_run:
                ready.append(subtask)
        
        return ready
    
    def get_subtask_by_id(self, subtask_id: str) -> Optional[SubTask]:
        """通过ID获取子任务"""
        for st in self.subtasks:
            if st.id == subtask_id:
                return st
        return None
    
    def is_complete(self) -> bool:
        """判断是否所有子任务都已完成"""
        return all(
            st.status in (SubTaskStatus.SUCCESS, SubTaskStatus.SKIPPED)
            for st in self.subtasks
        )
    
    def has_failed(self) -> bool:
        """判断是否有子任务失败"""
        return any(st.status == SubTaskStatus.FAILED for st in self.subtasks)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于序列化）"""
        return {
            "id": self.id,
            "original_request": self.original_request,
            "subtasks": [
                {
                    "id": st.id,
                    "goal": st.goal,
                    "order": st.order,
                    "status": st.status.value,
                    "depends_on": st.depends_on,
                    "error": st.error
                }
                for st in self.subtasks
            ],
            "metadata": self.metadata
        }

