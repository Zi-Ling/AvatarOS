"""
Event Bus Wrapper

Provides a clean abstraction over EventBus for planners and executors.
Handles event creation, publication, and error handling.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.avatar.runtime.events import EventBus

logger = logging.getLogger(__name__)

try:
    from app.avatar.runtime.events import Event, EventType
except ImportError:
    Event = None
    EventType = None


class EventBusWrapper:
    """
    EventBus 包装器
    
    提供统一的事件发布接口，处理：
    - Event 对象创建
    - 错误处理
    - 日志记录
    - 事件批量发送（未来扩展）
    """
    
    def __init__(self, event_bus: Optional[EventBus] = None, source: str = "planner"):
        """
        初始化 EventBusWrapper
        
        Args:
            event_bus: EventBus 实例（可选）
            source: 事件来源标识
        """
        self._event_bus = event_bus
        self._source = source
    
    def set_event_bus(self, event_bus: EventBus) -> None:
        """设置 EventBus 实例"""
        self._event_bus = event_bus
    
    def is_enabled(self) -> bool:
        """检查事件发布是否可用"""
        return self._event_bus is not None and Event is not None
    
    def publish(
        self,
        event_type: Any,
        payload: Dict[str, Any],
        *,
        step_id: Optional[str] = None,
        source: Optional[str] = None
    ) -> bool:
        """
        发布事件
        
        Args:
            event_type: 事件类型（EventType 枚举或字符串）
            payload: 事件负载
            step_id: 步骤 ID（可选）
            source: 事件来源（可选，默认使用初始化时的 source）
            
        Returns:
            是否成功发布
        """
        if not self.is_enabled():
            return False
        
        try:
            event = Event(
                type=event_type,
                source=source or self._source,
                step_id=step_id,
                payload=payload or {}
            )
            
            self._event_bus.publish(event)
            return True
            
        except Exception as e:
            logger.warning(f"Failed to publish event {event_type}: {e}")
            return False
    
    def publish_step_start(
        self,
        step_id: str,
        skill_name: str,
        params: Dict[str, Any],
        attempt: int = 1,
        max_attempts: int = 1
    ) -> None:
        """发布步骤开始事件"""
        if not EventType:
            return
        
        self.publish(
            EventType.STEP_START,
            {
                "skill": skill_name,
                "params": params,
                "attempt": attempt,
                "max_attempts": max_attempts
            },
            step_id=step_id
        )
    
    def publish_step_end(
        self,
        step_id: str,
        result: Any,
        duration: float = 0.0,
        summary: Optional[str] = None
    ) -> None:
        """发布步骤完成事件"""
        if not EventType:
            return
        
        payload = {
            "result": result,
            "duration": duration,
        }
        
        if summary:
            payload["summary"] = summary
        
        if isinstance(result, dict):
            payload["output_preview"] = str(result)[:100]
        
        self.publish(EventType.STEP_END, payload, step_id=step_id)
    
    def publish_step_failed(
        self,
        step_id: str,
        error: str,
        will_retry: bool = False,
        attempt: int = 1,
        max_attempts: int = 1
    ) -> None:
        """发布步骤失败事件"""
        if not EventType:
            return
        
        self.publish(
            EventType.STEP_FAILED,
            {
                "error": error,
                "will_retry": will_retry,
                "attempt": attempt,
                "max_attempts": max_attempts
            },
            step_id=step_id
        )
    
    def publish_task_decomposed(
        self,
        steps_summary: list,
        session_id: Optional[str] = None
    ) -> None:
        """发布任务分解事件"""
        if not EventType:
            return
        
        self.publish(
            EventType.TASK_DECOMPOSED,
            {
                "message": f"准备执行 {len(steps_summary)} 个步骤",
                "steps": steps_summary,
                "session_id": session_id
            }
        )
    
    def publish_subtask_start(
        self,
        subtask_id: str,
        goal: str,
        order: int,
        total: int,
        session_id: Optional[str] = None
    ) -> None:
        """发布子任务开始事件"""
        if not EventType:
            return
        
        self.publish(
            EventType.SUBTASK_START,
            {
                "subtask_id": subtask_id,
                "goal": goal,
                "order": order,
                "total": total,
                "session_id": session_id
            }
        )
    
    def publish_subtask_complete(
        self,
        subtask_id: str,
        goal: str,
        summary: str,
        skill_name: str,
        raw_output: Any = None,
        duration: float = 0.0,
        session_id: Optional[str] = None,
        error: Optional[str] = None
    ) -> None:
        """发布子任务完成事件"""
        if not EventType:
            return
        
        event_type = EventType.SUBTASK_COMPLETE if not error else EventType.SUBTASK_FAILED
        
        self.publish(
            event_type,
            {
                "subtask_id": subtask_id,
                "goal": goal,
                "summary": summary,
                "skill_name": skill_name,
                "raw_output": raw_output,
                "duration": duration,
                "session_id": session_id,
                "error": error
            }
        )
    
    def publish_file_operation(
        self,
        operation: str,
        path: str,
        file_type: str = "file",
        step_id: Optional[str] = None
    ) -> None:
        """
        发布文件系统操作事件
        
        Args:
            operation: 操作类型 (created, modified, deleted)
            path: 文件路径
            file_type: 文件类型 (file, directory)
            step_id: 步骤 ID
        """
        if not EventType:
            return
        
        event_type_map = {
            "created": EventType.FILE_CREATED if file_type == "file" else EventType.DIR_CREATED,
            "modified": EventType.FILE_MODIFIED,
            "deleted": EventType.FILE_DELETED if file_type == "file" else EventType.DIR_DELETED,
        }
        
        event_type = event_type_map.get(operation)
        if event_type:
            self.publish(
                event_type,
                {"path": path, "type": file_type},
                step_id=step_id
            )
    
    def publish_workflow_event(
        self,
        event_type: str,
        payload: Dict[str, Any]
    ) -> None:
        """
        发布工作流事件（字符串类型）
        
        用于不在标准 EventType 枚举中的自定义事件
        """
        if not self.is_enabled():
            return
        
        try:
            # 尝试匹配 EventType
            event_type_enum = None
            if EventType:
                try:
                    event_type_enum = EventType(event_type)
                except ValueError:
                    pass
            
            event = Event(
                type=event_type_enum or event_type,
                source=self._source,
                payload=payload
            )
            
            self._event_bus.publish(event)
            
        except Exception as e:
            logger.warning(f"Failed to publish workflow event: {e}")

