"""
事件发布器
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ...runtime.events import EventBus
    from ..models.subtask import CompositeTask, SubTask

logger = logging.getLogger(__name__)


class EventPublisher:
    """
    事件发布器
    
    职责：
    - 封装事件发布逻辑
    - 标准化事件格式
    - 提供便捷的发布方法
    """
    
    def __init__(self, event_bus: Optional[Any] = None):
        """
        Args:
            event_bus: 事件总线（可选）
        """
        self._event_bus = event_bus
    
    def publish_subtask_start(
        self,
        subtask: Any,
        total: int,
        session_id: Optional[str] = None
    ):
        """
        发布子任务开始事件
        
        Args:
            subtask: 子任务对象
            total: 总子任务数
            session_id: 会话ID（可选）
        """
        if not self._event_bus:
            return
        
        try:
            from ....runtime.events import Event, EventType
            self._event_bus.publish(Event(
                type=EventType.SUBTASK_START,
                source="orchestrator",
                payload={
                    "subtask_id": subtask.id,
                    "goal": subtask.goal,
                    "order": subtask.order,
                    "total": total,
                    "session_id": session_id
                }
            ))
        except Exception as e:
            logger.warning(f"Failed to publish SUBTASK_START event: {e}")
    
    def publish_subtask_complete(
        self,
        subtask: Any,
        summary: str,
        skill_name: Optional[str] = None,
        raw_output: Any = None,
        duration: float = 0,
        session_id: Optional[str] = None
    ):
        """
        发布子任务完成事件
        
        Args:
            subtask: 子任务对象
            summary: 任务总结（自然语言）
            skill_name: 技能名称（可选）
            raw_output: 原始输出（可选）
            duration: 执行耗时（可选）
            session_id: 会话ID（可选）
        """
        if not self._event_bus:
            return
        
        try:
            from ....runtime.events import Event, EventType
            self._event_bus.publish(Event(
                type=EventType.SUBTASK_COMPLETE,
                source="orchestrator",
                payload={
                    "subtask_id": subtask.id,
                    "goal": subtask.goal,
                    "summary": summary,
                    "skill_name": skill_name,
                    "raw_output": raw_output,
                    "duration": duration,
                    "session_id": session_id
                }
            ))
        except Exception as e:
            logger.warning(f"Failed to publish SUBTASK_COMPLETE event: {e}")
    
    def publish_subtask_failed(
        self,
        subtask: Any,
        error: str,
        session_id: Optional[str] = None
    ):
        """
        发布子任务失败事件
        
        Args:
            subtask: 子任务对象
            error: 错误信息
            session_id: 会话ID（可选）
        """
        if not self._event_bus:
            return
        
        try:
            from ....runtime.events import Event, EventType
            self._event_bus.publish(Event(
                type=EventType.SUBTASK_FAILED,
                source="orchestrator",
                payload={
                    "subtask_id": subtask.id,
                    "goal": subtask.goal,
                    "error": error,
                    "session_id": session_id
                }
            ))
        except Exception as e:
            logger.warning(f"Failed to publish SUBTASK_FAILED event: {e}")
    
    def publish_composite_task_complete(
        self,
        composite_task: Any,
        final_status: str,
        success_count: int,
        failed_count: int,
        total_count: int,
        session_id: Optional[str] = None
    ):
        """
        发布整体任务完成事件
        
        Args:
            composite_task: 复合任务对象
            final_status: 最终状态（success/partial_success/failed）
            success_count: 成功数
            failed_count: 失败数
            total_count: 总数
            session_id: 会话ID（可选）
        """
        if not self._event_bus:
            return
        
        try:
            from ....runtime.events import Event, EventType
            self._event_bus.publish(Event(
                type=EventType.COMPOSITE_TASK_COMPLETE,
                source="orchestrator",
                payload={
                    "task_id": composite_task.id,
                    "goal": composite_task.goal,
                    "status": final_status,
                    "success_count": success_count,
                    "failed_count": failed_count,
                    "total_count": total_count,
                    "session_id": session_id
                }
            ))
        except Exception as e:
            logger.warning(f"Failed to publish COMPOSITE_TASK_COMPLETE event: {e}")
    
    def publish_progress(
        self,
        composite_task: Any,
        completed_count: int,
        total_count: int,
        session_id: Optional[str] = None
    ):
        """
        发布进度更新事件
        
        Args:
            composite_task: 复合任务对象
            completed_count: 已完成数
            total_count: 总数
            session_id: 会话ID（可选）
        """
        if not self._event_bus:
            return
        
        try:
            from ....runtime.events import Event, EventType
            self._event_bus.publish(Event(
                type=EventType.COMPOSITE_TASK_PROGRESS,
                source="orchestrator",
                payload={
                    "task_id": composite_task.id,
                    "completed": completed_count,
                    "total": total_count,
                    "progress": completed_count / total_count if total_count > 0 else 0,
                    "session_id": session_id
                }
            ))
        except Exception as e:
            logger.warning(f"Failed to publish COMPOSITE_TASK_PROGRESS event: {e}")

