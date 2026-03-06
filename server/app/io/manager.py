import socketio
import logging
from collections import deque
from typing import Dict, Deque
import time

logger = logging.getLogger(__name__)

class SocketManager:
    """
    Singleton-like class to manage Socket.IO server instance.
    Separated to avoid circular imports and provide a clean interface.
    """
    _instance = None

    def __init__(self):
        # AsyncServer for integration with FastAPI (ASGI)
        # cors_allowed_origins='*' allows dev servers on different ports to connect
        self.server = socketio.AsyncServer(
            async_mode='asgi',
            cors_allowed_origins='*',
            logger=False,  # Set to True for debugging connection issues
            engineio_logger=False,
            # 增加超时时间以支持长时间任务（如多任务编排）
            ping_timeout=60,  # 60秒超时（支持长时间任务）
            ping_interval=20  # 20秒心跳间隔
        )
        self.app = socketio.ASGIApp(self.server)
        
        # 事件缓存：存储最近的重要事件（用于断线重连）
        # key: session_id, value: deque of (timestamp, event_name, data)
        self._event_cache: Dict[str, Deque] = {}
        self._cache_ttl = 300  # 缓存5分钟
        self._max_cache_size = 50  # 每个session最多缓存50个事件
        
        # Register default handlers
        self.server.on('connect', self.on_connect)
        self.server.on('disconnect', self.on_disconnect)
        self.server.on('request_missed_events', self.on_request_missed_events)
        self.server.on('cancel_task', self.on_cancel_task)
        self.server.on('approval_response', self.on_approval_response)

    @classmethod
    def get_instance(cls) -> 'SocketManager':
        if cls._instance is None:
            cls._instance = SocketManager()
        return cls._instance

    async def on_connect(self, sid, environ):
        logger.info(f"Client connected: {sid}")

    async def on_disconnect(self, sid):
        logger.info(f"Client disconnected: {sid}")
    
    async def on_request_missed_events(self, sid, data):
        """
        客户端重连后请求错过的事件
        data: {"session_id": "xxx", "last_event_time": timestamp}
        """
        try:
            session_id = data.get("session_id")
            last_event_time = data.get("last_event_time", 0)
            
            if not session_id or session_id not in self._event_cache:
                logger.info(f"No cached events for session {session_id}")
                return
            
            # 获取该session缓存的事件
            cached_events = self._event_cache[session_id]
            
            # 过滤出客户端错过的事件
            missed_events = [
                (ts, event_name, event_data)
                for ts, event_name, event_data in cached_events
                if ts > last_event_time
            ]
            
            logger.info(f"Replaying {len(missed_events)} missed events to client {sid}")
            
            # 重发错过的事件
            for ts, event_name, event_data in missed_events:
                await self.server.emit(event_name, event_data, room=sid)
                logger.debug(f"Replayed event {event_name} to {sid}")
            
        except Exception as e:
            logger.error(f"Failed to replay missed events: {e}")
    
    async def on_cancel_task(self, sid, data):
        """
        处理客户端取消任务请求
        data: {"session_id": "xxx", "task_id": "xxx"}
        """
        try:
            from app.api.chat.cancellation import get_cancellation_manager
            
            session_id = data.get("session_id")
            task_id = data.get("task_id")
            
            logger.info(f"📛 [SocketManager] 收到取消请求 - Client: {sid}, Session: {session_id}, Task: {task_id}")
            
            cancellation_mgr = get_cancellation_manager()
            
            # 取消会话（停止 Chat 流式输出）
            if session_id:
                cancellation_mgr.cancel_session(session_id)
            
            # 取消任务（停止 Task 执行）
            if task_id:
                success = cancellation_mgr.cancel_task(task_id)
                
                # 发送取消确认事件
                await self.emit("server_event", {
                    "type": "task.cancelled",
                    "payload": {
                        "session_id": session_id,
                        "task_id": task_id,
                        "message": "任务已取消" if success else "任务已结束或不存在"
                    }
                })
            else:
                # 如果没有指定 task_id，取消会话的所有任务
                cancelled_count = cancellation_mgr.cancel_all_session_tasks(session_id)
                
                await self.emit("server_event", {
                    "type": "task.cancelled",
                    "payload": {
                        "session_id": session_id,
                        "message": f"已取消 {cancelled_count} 个任务"
                    }
                })
            
            logger.info(f"✅ [SocketManager] 取消请求已处理")
            
        except Exception as e:
            logger.error(f"❌ [SocketManager] 处理取消请求失败: {e}", exc_info=True)
    
    async def on_approval_response(self, sid, data):
        """
        处理客户端审批响应
        data: {"request_id": "xxx", "approved": bool, "user_comment": "xxx"}
        """
        try:
            from app.services.approval_service import get_approval_service
            
            request_id = data.get("request_id")
            approved = data.get("approved", False)
            user_comment = data.get("user_comment")
            
            logger.info(f"✅ [SocketManager] 收到审批响应 - Client: {sid}, Request: {request_id}, Approved: {approved}")
            
            service = get_approval_service()
            success = service.respond(
                request_id=request_id,
                approved=approved,
                user_comment=user_comment
            )
            
            if success:
                # 发送审批确认事件
                await self.emit("server_event", {
                    "type": "approval.responded",
                    "payload": {
                        "request_id": request_id,
                        "approved": approved,
                        "message": "审批已处理"
                    }
                })
                logger.info(f"✅ [SocketManager] 审批响应已处理")
            else:
                logger.warning(f"⚠️ [SocketManager] 审批响应失败 - Request: {request_id}")
                await self.emit("server_event", {
                    "type": "approval.error",
                    "payload": {
                        "request_id": request_id,
                        "message": "审批请求不存在或已过期"
                    }
                })
            
        except Exception as e:
            logger.error(f"❌ [SocketManager] 处理审批响应失败: {e}", exc_info=True)

    async def emit(self, event: str, data: dict, room: str = None):
        """
        Wrapper around emit to handle async emission safely.
        同时缓存重要事件用于断线重连。
        """
        try:
            # emit is awaitable in AsyncServer
            await self.server.emit(event, data, room=room)
            
            # 缓存重要事件（TASK_COMPLETED, PLAN_GENERATED等）
            if event == "server_event":
                self._cache_event(data)
                
        except Exception as e:
            logger.error(f"Failed to emit socket event '{event}': {e}")
    
    def _cache_event(self, event_data: dict):
        """
        缓存重要事件用于断线重连
        只缓存 TASK_COMPLETED, PLAN_GENERATED, SYSTEM_ERROR 等关键事件
        """
        try:
            event_type = event_data.get("type", "")
            
            # 只缓存关键事件
            important_events = [
                "task.completed",
                "plan.generated", 
                "system.error"
            ]
            
            if event_type not in important_events:
                return
            
            # 从payload中提取session_id（如果有）
            payload = event_data.get("payload", {})
            
            # 尝试从不同位置获取session_id
            session_id = None
            if "composite_task" in payload:
                session_id = payload["composite_task"].get("metadata", {}).get("session_id")
            elif "task" in payload:
                task_data = payload["task"]
                if isinstance(task_data, dict):
                    session_id = task_data.get("metadata", {}).get("session_id")
            
            if not session_id:
                # 如果没有session_id，使用默认缓存
                session_id = "_default"
            
            # 初始化该session的缓存队列
            if session_id not in self._event_cache:
                self._event_cache[session_id] = deque(maxlen=self._max_cache_size)
            
            # 添加到缓存
            timestamp = time.time()
            self._event_cache[session_id].append((timestamp, "server_event", event_data))
            
            # Removed verbose debug log - too noisy
            # logger.debug(f"Cached {event_type} event for session {session_id}")
            
            # 清理过期缓存
            self._cleanup_old_cache()
            
        except Exception as e:
            logger.error(f"Failed to cache event: {e}")
    
    def _cleanup_old_cache(self):
        """清理过期的缓存事件"""
        try:
            current_time = time.time()
            sessions_to_remove = []
            
            for session_id, events in self._event_cache.items():
                # 移除过期事件
                while events and current_time - events[0][0] > self._cache_ttl:
                    events.popleft()
                
                # 如果队列为空，标记删除
                if not events:
                    sessions_to_remove.append(session_id)
            
            # 删除空队列
            for session_id in sessions_to_remove:
                del self._event_cache[session_id]
                
        except Exception as e:
            logger.error(f"Failed to cleanup cache: {e}")

