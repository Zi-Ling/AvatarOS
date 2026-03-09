# app/api/chat/cancellation.py
"""
取消管理器：管理活跃的聊天会话和任务取消请求
"""
import asyncio
import threading
from typing import Dict, Set
import logging

logger = logging.getLogger(__name__)


class CancellationManager:
    """
    管理活跃会话和任务的取消状态
    
    支持：
    - Chat 流式输出取消
    - Task 执行取消
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __init__(self):
        # 活跃的会话ID（用于Chat取消）
        # key: session_id, value: threading.Event
        self._active_sessions: Dict[str, threading.Event] = {}
        
        # 活跃的任务ID（用于Task取消）
        # key: task_id, value: threading.Event
        self._active_tasks: Dict[str, threading.Event] = {}
        
        # 会话到任务的映射（用于从session_id找到task_id）
        # key: session_id, value: set of task_ids
        self._session_tasks: Dict[str, Set[str]] = {}
    
    @classmethod
    def get_instance(cls) -> 'CancellationManager':
        """获取单例实例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = CancellationManager()
        return cls._instance
    
    # === Session管理（用于Chat流式输出） ===
    
    def register_session(self, session_id: str) -> threading.Event:
        """
        注册一个活跃会话
        
        返回一个 Event，可以用于检查是否被取消
        """
        cancel_event = threading.Event()
        self._active_sessions[session_id] = cancel_event
        logger.debug(f"[CancellationManager] 注册会话: {session_id}")
        return cancel_event
    
    def unregister_session(self, session_id: str):
        """取消注册会话（会话结束时调用）"""
        if session_id in self._active_sessions:
            del self._active_sessions[session_id]
            logger.debug(f"[CancellationManager] 取消注册会话: {session_id}")
    
    def cancel_session(self, session_id: str) -> bool:
        """
        取消指定会话
        
        返回: 是否成功设置取消标志
        """
        if session_id in self._active_sessions:
            self._active_sessions[session_id].set()
            logger.info(f"[CancellationManager] 已设置会话取消标志: {session_id}")
            return True
        else:
            logger.warning(f"[CancellationManager] 会话不存在或已结束: {session_id}")
            return False
    
    def is_session_cancelled(self, session_id: str) -> bool:
        """检查会话是否被取消"""
        event = self._active_sessions.get(session_id)
        return event.is_set() if event else False
    
    # === Task管理（用于任务执行） ===
    
    def register_task(self, task_id: str, session_id: str = None) -> threading.Event:
        """
        注册一个活跃任务
        
        返回一个 Event，可以用于检查是否被取消
        """
        cancel_event = threading.Event()
        self._active_tasks[task_id] = cancel_event
        
        # 关联到会话
        if session_id:
            if session_id not in self._session_tasks:
                self._session_tasks[session_id] = set()
            self._session_tasks[session_id].add(task_id)
        
        logger.debug(f"[CancellationManager] 注册任务: {task_id} (session: {session_id})")
        return cancel_event
    
    def alias_task(self, alias_id: str, task_id: str) -> bool:
        """
        为已注册的任务添加别名 ID（复用同一个 cancel event）。
        用于把 graph_id 关联到已注册的 intent_id，让前端用 graph_id 也能取消。
        
        Returns: 是否成功（task_id 不存在时返回 False）
        """
        event = self._active_tasks.get(task_id)
        if event is None:
            logger.warning(f"[CancellationManager] alias_task: task {task_id} not found")
            return False
        self._active_tasks[alias_id] = event
        logger.debug(f"[CancellationManager] 注册别名: {alias_id} → {task_id}")
        return True

    def unregister_task(self, task_id: str):
        """取消注册任务（任务结束时调用）"""
        if task_id in self._active_tasks:
            del self._active_tasks[task_id]
            logger.debug(f"[CancellationManager] 取消注册任务: {task_id}")
            
        # 从会话映射中移除
        for session_id, task_ids in self._session_tasks.items():
            if task_id in task_ids:
                task_ids.remove(task_id)
    
    def cancel_task(self, task_id: str) -> bool:
        """
        取消指定任务
        
        返回: 是否成功设置取消标志
        """
        if task_id in self._active_tasks:
            self._active_tasks[task_id].set()
            logger.info(f"[CancellationManager] 已设置任务取消标志: {task_id}")
            return True
        else:
            logger.warning(f"[CancellationManager] 任务不存在或已结束: {task_id}")
            return False
    
    def is_task_cancelled(self, task_id: str) -> bool:
        """检查任务是否被取消"""
        event = self._active_tasks.get(task_id)
        return event.is_set() if event else False
    
    def get_session_tasks(self, session_id: str) -> Set[str]:
        """获取会话关联的所有任务ID"""
        return self._session_tasks.get(session_id, set()).copy()
    
    def cancel_all_session_tasks(self, session_id: str) -> int:
        """
        取消会话关联的所有任务
        
        返回: 取消的任务数量
        """
        task_ids = self.get_session_tasks(session_id)
        cancelled_count = 0
        
        for task_id in task_ids:
            if self.cancel_task(task_id):
                cancelled_count += 1
        
        logger.info(f"[CancellationManager] 取消了会话 {session_id} 的 {cancelled_count} 个任务")
        return cancelled_count
    
    def get_active_sessions_count(self) -> int:
        """获取活跃会话数量"""
        return len(self._active_sessions)
    
    def get_active_tasks_count(self) -> int:
        """获取活跃任务数量"""
        return len(self._active_tasks)


# 全局单例实例
_cancellation_manager = None


def get_cancellation_manager() -> CancellationManager:
    """获取取消管理器的全局实例（用于依赖注入）"""
    global _cancellation_manager
    if _cancellation_manager is None:
        _cancellation_manager = CancellationManager.get_instance()
    return _cancellation_manager

