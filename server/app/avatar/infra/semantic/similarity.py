"""
Semantic Similarity Utilities

提供各种语义相似度计算方法
"""
import numpy as np
from typing import List, Tuple
import logging

logger = logging.getLogger(__name__)


class SemanticSimilarity:
    """
    语义相似度工具类
    
    提供多种相似度计算方法（余弦、欧氏距离、点积）
    """
    
    @staticmethod
    def cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
        """
        计算余弦相似度
        
        Returns:
            float: 相似度分数 [0, 1]，1表示完全相同
        """
        try:
            # 归一化
            vec1_norm = vec1 / np.linalg.norm(vec1)
            vec2_norm = vec2 / np.linalg.norm(vec2)
            
            # 点积
            similarity = np.dot(vec1_norm, vec2_norm)
            
            # 确保在 [0, 1] 范围内
            return float(np.clip(similarity, 0.0, 1.0))
        except Exception as e:
            logger.error(f"Cosine similarity calculation failed: {e}")
            return 0.0
    
    @staticmethod
    def euclidean_distance(vec1: np.ndarray, vec2: np.ndarray) -> float:
        """
        计算欧氏距离
        
        Returns:
            float: 距离值，越小越相似
        """
        try:
            return float(np.linalg.norm(vec1 - vec2))
        except Exception as e:
            logger.error(f"Euclidean distance calculation failed: {e}")
            return float('inf')
    
    @staticmethod
    def dot_product_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
        """
        计算点积相似度
        
        Returns:
            float: 相似度分数
        """
        try:
            return float(np.dot(vec1, vec2))
        except Exception as e:
            logger.error(f"Dot product calculation failed: {e}")
            return 0.0
    
    @staticmethod
    def find_most_similar(
        query_vec: np.ndarray,
        candidate_vecs: List[np.ndarray],
        method: str = "cosine"
    ) -> Tuple[int, float]:
        """
        在候选向量中找到最相似的一个
        
        Args:
            query_vec: 查询向量
            candidate_vecs: 候选向量列表或numpy数组
            method: 相似度计算方法 ("cosine" / "euclidean" / "dot")
        
        Returns:
            (index, score): 最相似的索引和分数
        """
        # 处理空列表或数组
        if isinstance(candidate_vecs, np.ndarray):
            if len(candidate_vecs) == 0:
                return -1, 0.0
        elif not candidate_vecs:
            return -1, 0.0
        
        scores = []
        for vec in candidate_vecs:
            if method == "cosine":
                score = SemanticSimilarity.cosine_similarity(query_vec, vec)
            elif method == "euclidean":
                # 欧氏距离：转换为相似度（距离越小，相似度越高）
                dist = SemanticSimilarity.euclidean_distance(query_vec, vec)
                score = 1.0 / (1.0 + dist)
            elif method == "dot":
                score = SemanticSimilarity.dot_product_similarity(query_vec, vec)
            else:
                raise ValueError(f"Unknown similarity method: {method}")
            
            scores.append(score)
        
        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])
        
        return best_idx, best_score
    
    @staticmethod
    def rank_by_similarity(
        query_vec: np.ndarray,
        candidate_vecs: List[np.ndarray],
        top_k: int = 5,
        method: str = "cosine"
    ) -> List[Tuple[int, float]]:
        """
        按相似度排序候选向量
        
        Args:
            query_vec: 查询向量
            candidate_vecs: 候选向量列表或numpy数组
            top_k: 返回前K个
            method: 相似度计算方法
        
        Returns:
            [(index, score), ...]: 排序后的结果
        """
        # 处理空列表或数组
        if isinstance(candidate_vecs, np.ndarray):
            if len(candidate_vecs) == 0:
                return []
        elif not candidate_vecs:
            return []
        
        scores = []
        for i, vec in enumerate(candidate_vecs):
            if method == "cosine":
                score = SemanticSimilarity.cosine_similarity(query_vec, vec)
            elif method == "euclidean":
                dist = SemanticSimilarity.euclidean_distance(query_vec, vec)
                score = 1.0 / (1.0 + dist)
            elif method == "dot":
                score = SemanticSimilarity.dot_product_similarity(query_vec, vec)
            else:
                raise ValueError(f"Unknown similarity method: {method}")
            
            scores.append((i, score))
        
        # 按分数降序排序
        scores.sort(key=lambda x: x[1], reverse=True)
        
        return scores[:top_k]

