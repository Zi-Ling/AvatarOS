"""
RAG Retriever

Retrieves similar successful task cases for context.
"""
from __future__ import annotations

import logging
from typing import Any, List, Dict, Optional

logger = logging.getLogger(__name__)


class RAGRetriever:
    """
    RAG 检索器
    
    检索相似的成功任务案例，用于辅助规划
    """
    
    def __init__(self, memory_manager: Optional[Any] = None):
        """
        初始化 RAG 检索器
        
        Args:
            memory_manager: MemoryManager 实例（需要支持 search_similar_tasks）
        """
        self.memory_manager = memory_manager
    
    def retrieve_similar_cases(
        self,
        goal_text: str,
        raw_input: str,
        *,
        n_results: int = 3,
        min_relevance: float = 0.25  # 主题相关性阈值（distance < 0.75）
    ) -> List[Dict[str, Any]]:
        """
        检索相似的成功案例（带主题过滤）
        
        优化策略：
        1. 提高相似度阈值：只保留高度相关的案例
        2. 如果没有相关案例，返回空（避免误导 LLM）
        3. 防止"模式坍塌"：低相关案例会让 LLM 套用错误模板
        
        Args:
            goal_text: 目标描述
            raw_input: 原始用户输入
            n_results: 返回结果数量
            min_relevance: 最低相关度（0-1，越高越严格）
            
        Returns:
            相似案例列表 [{"document": str, "distance": float, "metadata": dict}, ...]
        """
        if not self.memory_manager:
            return []
        
        try:
            # 组合查询
            task_query = f"{goal_text} {raw_input}"
            
            # 执行相似度搜索（检索更多候选，后续过滤）
            similar_cases = self.memory_manager.search_similar_tasks(
                task_description=task_query,
                n_results=n_results * 3,  # 检索3倍数量，再过滤
            )
            
            if not similar_cases:
                return []
            
            # 主题相关性过滤
            max_distance = 1 - min_relevance  # distance 越小越相似
            relevant_cases = [
                case for case in similar_cases
                if case.get('distance', 1.0) < max_distance
            ]
            
            if not relevant_cases:
                logger.debug(
                    f"RAGRetriever: No relevant cases found "
                    f"(all {len(similar_cases)} cases have distance > {max_distance:.2f}), "
                    f"falling back to pure prompt"
                )
                return []
            
            relevant_cases = relevant_cases[:n_results]
            
            logger.debug(
                f"RAGRetriever: Retrieved {len(relevant_cases)} relevant cases "
                f"(filtered from {len(similar_cases)}, distance_threshold={max_distance:.2f})"
            )
            self._debug_print_cases(relevant_cases)
            
            return relevant_cases
            
        except Exception as e:
            logger.debug(f"RAGRetriever: Failed to retrieve similar cases: {e}")
            return []
    
    def _debug_print_cases(self, cases: List[Dict[str, Any]]) -> None:
        """调试输出检索到的案例"""
        for i, case in enumerate(cases):
            distance = case.get('distance', 999) if case.get('distance') is not None else 999
            doc_preview = case.get('document', '')[:100].replace('\n', ' ')
            logger.debug(f"  [{i+1}] Distance: {distance:.3f}, Doc: {doc_preview}...")

