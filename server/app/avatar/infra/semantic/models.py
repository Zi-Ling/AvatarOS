"""
Semantic Models

语义服务的数据模型
"""
from dataclasses import dataclass
from typing import List, Optional
import numpy as np


@dataclass
class EmbeddingResult:
    """嵌入结果"""
    text: str
    vector: np.ndarray
    model: str
    
    @property
    def dimension(self) -> int:
        """向量维度"""
        return len(self.vector)


@dataclass
class SimilarityResult:
    """相似度计算结果"""
    text1: str
    text2: str
    score: float
    method: str  # "cosine" / "euclidean" / "dot"
    
    def is_similar(self, threshold: float = 0.7) -> bool:
        """判断是否相似"""
        return self.score >= threshold


@dataclass
class SemanticMatch:
    """语义匹配结果"""
    query: str
    matched_text: str
    score: float
    rank: int  # 排名（从1开始）

