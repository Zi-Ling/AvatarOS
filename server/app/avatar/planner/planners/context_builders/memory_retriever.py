"""
Memory Retriever

Retrieves conversation context and user preferences from Memory system.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class MemoryRetriever:
    """
    记忆检索器
    
    从 MemoryManager 和 LearningManager 获取上下文信息
    """
    
    def __init__(self, memory_manager: Optional[Any] = None, learning_manager: Optional[Any] = None):
        """
        初始化记忆检索器
        
        Args:
            memory_manager: MemoryManager 实例
            learning_manager: LearningManager 实例
        """
        self.memory_manager = memory_manager
        self.learning_manager = learning_manager
    
    def retrieve_conversation_context(self, intent: Any) -> Optional[Dict[str, Any]]:
        """
        获取对话上下文
        
        优先级:
        1. 从 MemoryManager 获取（主路径）
        2. 从 intent.metadata 获取（降级路径）
        
        Args:
            intent: IntentSpec 对象
            
        Returns:
            对话上下文字典或 None
        """
        conversation_context = None
        
        # 1. 尝试从 MemoryManager 获取
        if self.memory_manager:
            session_id = self._extract_session_id(intent)
            
            if session_id:
                try:
                    key = f"conv:{session_id}:messages"
                    conv_state = self.memory_manager.get_working_state(key)
                    
                    if conv_state:
                        conversation_context = conv_state
                        logger.debug(f"MemoryRetriever: Retrieved conversation context "
                              f"with {len(conv_state.get('messages', []))} messages")
                except Exception as e:
                    logger.debug(f"MemoryRetriever: Failed to retrieve conversation context: {e}")
        
        # 2. 降级：从 intent.metadata 获取
        if not conversation_context and hasattr(intent, 'metadata'):
            chat_history = intent.metadata.get('chat_history')
            if chat_history:
                conversation_context = {"messages": chat_history}
                logger.debug(f"MemoryRetriever: Retrieved conversation context from "
                      f"intent metadata (fallback): {len(chat_history)} messages")
        
        # 3. 调试输出
        if conversation_context:
            self._debug_print_context(conversation_context)
        
        return conversation_context
    
    def retrieve_user_preferences(self, intent: Any) -> Optional[Dict[str, Any]]:
        """
        获取用户偏好
        
        从 LearningManager 获取（不直接从 Memory 获取）
        
        Args:
            intent: IntentSpec 对象
            
        Returns:
            用户偏好字典或 None
        """
        if not self.learning_manager:
            return None
        
        user_id = self._extract_user_id(intent)
        
        try:
            user_preferences = self.learning_manager.get_user_preferences(user_id)
            if user_preferences:
                logger.debug(f"MemoryRetriever: Retrieved user preferences "
                      f"from Learning: {user_preferences}")
                return user_preferences
        except Exception as e:
            logger.debug(f"MemoryRetriever: Failed to retrieve user preferences: {e}")
        
        return None
    
    def _extract_session_id(self, intent: Any) -> Optional[str]:
        """从 intent 提取 session_id"""
        if not hasattr(intent, 'metadata') or not intent.metadata:
            return None
        
        return intent.metadata.get('conversation_id') or intent.metadata.get('session_id')
    
    def _extract_user_id(self, intent: Any) -> str:
        """从 intent 提取 user_id（带默认值）"""
        if hasattr(intent, 'metadata') and intent.metadata:
            user_id = intent.metadata.get('user_id')
            if user_id:
                return user_id
        
        return "default"  # 默认用户
    
    def _debug_print_context(self, conversation_context: Dict[str, Any]) -> None:
        """调试输出对话上下文内容"""
        messages = conversation_context.get("messages", [])
        if messages:
            try:
                logger.debug(f"MemoryRetriever: History Content Dump: "
                      f"{json.dumps(messages, ensure_ascii=False, indent=2)}")
            except Exception:
                logger.debug(f"MemoryRetriever: History Content Dump: {messages}")

