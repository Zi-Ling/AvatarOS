# app/avatar/runtime/core/base_executor.py
"""
执行器基类和协议
"""
from __future__ import annotations

import logging
from typing import Protocol, Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.avatar.intent.models import IntentSpec
    from app.avatar.runtime.core.result import AgentLoopResult
    from app.avatar.runtime.events import EventBus, EventType

logger = logging.getLogger(__name__)


class ExecutorProtocol(Protocol):
    """执行器协议"""
    
    async def execute(
        self, 
        intent: IntentSpec, 
        env_context: dict
    ) -> AgentLoopResult:
        """执行任务"""
        ...


class BaseExecutor:
    """
    执行器基类
    提供通用的事件发布和错误处理逻辑
    """
    
    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        logger_instance: Optional[logging.Logger] = None,
    ):
        self.event_bus = event_bus
        self.logger = logger_instance or logger
    
    def _emit_event(
        self, 
        event_type: EventType, 
        payload: Optional[dict] = None, 
        step_id: Optional[str] = None
    ) -> None:
        """统一的事件发布逻辑"""
        if not self.event_bus:
            return
        
        try:
            from app.avatar.runtime.events import Event
            
            payload = payload or {}
            # Removed verbose debug log - too noisy
            # self.logger.debug(
            #     f"[{self.__class__.__name__}] Emitting event: {event_type.value}"
            # )
            
            event = Event(
                type=event_type,
                source=self.__class__.__name__.lower(),
                payload=payload,
                step_id=step_id
            )
            
            self.event_bus.publish(event)
            
        except Exception as e:
            self.logger.error(f"Failed to emit event {event_type.value}: {e}")
    
    def _handle_error(self, error: Exception, context: dict) -> None:
        """统一的错误处理逻辑"""
        self.logger.error(
            f"[{self.__class__.__name__}] Error: {error}",
            extra=context
        )

