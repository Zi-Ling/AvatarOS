"""
Semantic Infrastructure Module

提供语义能力的基础设施，包括：
- EmbeddingService: 嵌入模型服务（全局单例）
- SemanticSimilarity: 相似度计算工具
- 数据模型：EmbeddingResult, SimilarityResult, SemanticMatch

使用示例：
```python
from app.avatar.infra.semantic import get_embedding_service, similarity

# 获取服务
service = get_embedding_service()
service.initialize()  # 启动时初始化

# 使用
vec = service.embed_single("你好")
score = similarity("你好", "您好")
```
"""

from .service import EmbeddingService, get_embedding_service
from .similarity import SemanticSimilarity
from .models import EmbeddingResult, SimilarityResult, SemanticMatch


# 便捷函数
def embed(text: str):
    """快捷方式：嵌入单个文本"""
    return get_embedding_service().embed_single(text)


def embed_batch(texts: list[str]):
    """快捷方式：批量嵌入"""
    return get_embedding_service().embed_batch(texts)


def similarity(text1: str, text2: str, method: str = "cosine") -> float:
    """快捷方式：计算相似度"""
    return get_embedding_service().similarity(text1, text2, method=method)


def find_similar(query: str, candidates: list[str], threshold: float = 0.7):
    """快捷方式：找到最相似的文本"""
    return get_embedding_service().find_most_similar(query, candidates, threshold)


__all__ = [
    # 核心类
    "EmbeddingService",
    "SemanticSimilarity",
    
    # 数据模型
    "EmbeddingResult",
    "SimilarityResult",
    "SemanticMatch",
    
    # 工厂函数
    "get_embedding_service",
    
    # 便捷函数
    "embed",
    "embed_batch",
    "similarity",
    "find_similar",
]

