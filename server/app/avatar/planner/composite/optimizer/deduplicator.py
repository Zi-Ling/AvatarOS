"""
子任务去重器
"""
from __future__ import annotations

import logging
from typing import List, Optional, Any

from ...models.subtask import SubTask

logger = logging.getLogger(__name__)


class SubTaskDeduplicator:
    """
    子任务去重器
    
    职责：
    - 使用语义相似度检测重复的子任务
    - 合并相似的子任务
    """
    
    def __init__(self, embedding_service: Optional[Any] = None, threshold: float = 0.9):
        """
        Args:
            embedding_service: 语义向量服务（可选）
            threshold: 相似度阈值（>= 该值认为是重复）
        """
        self._embedding_service = embedding_service
        self._threshold = threshold
    
    def deduplicate(self, subtasks: List[SubTask]) -> List[SubTask]:
        """
        去除重复的子任务
        
        Args:
            subtasks: 子任务列表
        
        Returns:
            List[SubTask]: 去重后的子任务列表
        """
        if not self._embedding_service or not self._embedding_service.is_available():
            # 如果没有语义服务，直接返回原列表
            logger.debug("Embedding service not available, skipping deduplication")
            return subtasks
        
        if len(subtasks) <= 1:
            return subtasks
        
        deduplicated = []
        skip_indices = set()
        
        for i, st1 in enumerate(subtasks):
            if i in skip_indices:
                continue
            
            # 检查是否与已添加的任务重复
            is_duplicate = False
            for j in range(i + 1, len(subtasks)):
                if j in skip_indices:
                    continue
                
                st2 = subtasks[j]
                similarity = self._embedding_service.similarity(st1.goal, st2.goal)
                
                if similarity >= self._threshold:
                    # 发现重复
                    logger.info(
                        f"Duplicate subtask detected: '{st1.goal}' ~ '{st2.goal}' "
                        f"(similarity={similarity:.3f})"
                    )
                    skip_indices.add(j)
                    is_duplicate = True
            
            if not is_duplicate:
                deduplicated.append(st1)
        
        removed_count = len(subtasks) - len(deduplicated)
        if removed_count > 0:
            logger.info(f"Removed {removed_count} duplicate subtask(s)")
        
        return deduplicated

