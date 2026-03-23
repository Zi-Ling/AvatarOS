# app/services/knowledge/embedding.py
"""Embedding 适配层 — 抽象接口 + ChromaDB 默认实现"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """抽象 embedding 接口，支持可插拔模型。"""

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量 embedding。"""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """单条 embedding（用于查询）。"""

    @abstractmethod
    def dimension(self) -> int:
        """返回 embedding 维度。"""


class ChromaEmbeddingProvider(EmbeddingProvider):
    """
    ChromaDB 内置 all-MiniLM-L6-v2。
    实际 ingest/query 时让 ChromaDB 自动调用 embedding，
    此类主要用于维度校验和未来 provider 替换。
    """

    def __init__(self):
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
        self._fn = DefaultEmbeddingFunction()
        # 探测维度：用固定非空文本，避免空字符串触发特殊处理
        sample = self._fn(["test"])
        self._dim = len(sample[0])
        logger.info(f"ChromaEmbeddingProvider initialized, dim={self._dim}")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._fn(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._fn([text])[0]

    def dimension(self) -> int:
        return self._dim
