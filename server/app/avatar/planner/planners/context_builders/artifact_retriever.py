"""
Artifact Retriever

Retrieves recent artifacts from the session context.
"""
from __future__ import annotations

import logging
from typing import Any, List, Dict, Optional

logger = logging.getLogger(__name__)


class ArtifactRetriever:
    """
    Artifact 检索器
    
    从 Session 上下文获取最近的 Artifacts
    """
    
    def __init__(self, memory_manager: Optional[Any] = None):
        """
        初始化 Artifact 检索器
        
        Args:
            memory_manager: MemoryManager 实例
        """
        self.memory_manager = memory_manager
    
    def retrieve_recent_artifacts(
        self,
        intent: Any,
        *,
        max_count: int = 5
    ) -> List[Dict[str, Any]]:
        """
        获取最近的 Artifacts + 上一个任务的结构化结果
        
        Args:
            intent: IntentSpec 对象
            max_count: 最大数量
            
        Returns:
            Artifact 列表（包含结构化的上下文信息）
        """
        if not self.memory_manager:
            return []
        
        # 提取 session_id
        session_id = self._extract_session_id(intent)
        if not session_id:
            return []
        
        try:
            # 获取 Session 上下文
            session_data = self.memory_manager.get_session_context(session_id)
            
            if not session_data:
                return []
            
            results = []
            
            # 1. 获取上一个任务的结构化结果（最有价值的上下文）
            variables = session_data.get("variables", {})
            last_task_result = variables.get("last_task_result")
            if last_task_result and isinstance(last_task_result, dict):
                results.append({
                    "type": "previous_task_result",
                    "description": f"上一个任务: {last_task_result.get('goal', '')}",
                    "status": last_task_result.get("status", ""),
                    "output_path": last_task_result.get("output_path", ""),
                })
            
            # 2. 获取 artifact 列表
            all_artifacts = session_data.get("artifacts", [])
            if all_artifacts:
                recent_artifacts = all_artifacts[-max_count:] if len(all_artifacts) > max_count else all_artifacts
                for art in recent_artifacts:
                    results.append({
                        "type": art.get("type", "unknown"),
                        "path": art.get("uri", ""),
                        "meta": art.get("meta", {}),
                    })
            
            return results
            
        except Exception as e:
            logger.debug(f"ArtifactRetriever: Failed to retrieve artifacts: {e}")
            return []
    
    def _extract_session_id(self, intent: Any) -> Optional[str]:
        """从 intent 提取 session_id"""
        if not hasattr(intent, 'metadata') or not intent.metadata:
            return None
        
        return intent.metadata.get('session_id') or intent.metadata.get('conversation_id')

