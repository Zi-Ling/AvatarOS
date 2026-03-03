"""
语义匹配策略
"""
from __future__ import annotations

import logging
from typing import Any, Optional, Dict, Tuple

logger = logging.getLogger(__name__)


class SemanticMatchStrategy:
    """
    使用语义相似度匹配字段
    """
    
    def __init__(self, embedding_service: Any):
        """
        Args:
            embedding_service: 语义向量服务
        """
        self._embedding_service = embedding_service
    
    def extract(
        self,
        output_name: str,
        raw_output: Dict[str, Any],
        threshold: float = 0.7
    ) -> Optional[Any]:
        """
        语义匹配提取
        
        Args:
            output_name: 期望的输出字段名
            raw_output: 原始输出字典
            threshold: 相似度阈值
        
        Returns:
            提取的值，如果失败返回 None
        """
        if not isinstance(raw_output, dict) or len(raw_output) <= 1:
            return None
        
        if not self._embedding_service or not self._embedding_service.is_available():
            return None
        
        try:
            # 计算期望字段的 embedding
            from app.avatar.infra.semantic.similarity import SemanticSimilarity
            
            expected_vec = self._embedding_service.embed_single(output_name)
            
            # 计算所有候选字段的相似度
            best_field = None
            best_score = 0.0
            
            for field_name in raw_output.keys():
                field_vec = self._embedding_service.embed_single(field_name)
                score = SemanticSimilarity.cosine_similarity(expected_vec, field_vec)
                
                if score > best_score:
                    best_score = score
                    best_field = field_name
            
            # 检查是否超过阈值
            if best_score >= threshold and best_field:
                logger.info(
                    f"✅ Extracted '{output_name}' via semantic_match "
                    f"(matched: '{best_field}', similarity={best_score:.3f})"
                )
                return raw_output[best_field]
            
            return None
            
        except Exception as e:
            logger.warning(f"Semantic field matching failed: {e}")
            return None

