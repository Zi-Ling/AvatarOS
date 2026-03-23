# app/services/knowledge/search_service.py
"""知识库搜索服务 — 语义搜索 + 混合搜索 + passage 合并"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.services.knowledge.doc_store import KnowledgeDocumentStore

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """标准化搜索结果"""
    document_id: str
    chunk_id: str
    text: str
    score: float          # normalized relevance score, 0-1
    metadata: dict
    source_title: str
    chunk_index: int


@dataclass
class PassageResult:
    """合并后的 passage 结果"""
    document_id: str
    source_title: str
    text: str
    score: float
    chunk_ids: list[str] = field(default_factory=list)
    chunk_indices: list[int] = field(default_factory=list)


class KnowledgeSearchService:
    def __init__(self, chroma_client, doc_store: KnowledgeDocumentStore):
        self._client = chroma_client
        self._doc_store = doc_store

    def _get_collection(self, name: str = "avatar_knowledge"):
        return self._client.get_or_create_collection(name=name)

    @staticmethod
    def _distance_to_score(distance: float) -> float:
        """ChromaDB L2 distance → normalized relevance score (0,1]"""
        return 1.0 / (1.0 + distance)

    async def semantic_search(
        self,
        query: str,
        top_k: int = 5,
        collection_name: str = "avatar_knowledge",
        filters: dict | None = None,
        score_threshold: float = 0.0,
    ) -> list[SearchResult]:
        """
        语义搜索：
        1. 获取未删除文档 ID 集合
        2. ChromaDB query
        3. distance → score 转换
        4. 过滤已删除文档 + 阈值过滤
        5. 降序排列
        """
        active_ids = self._doc_store.get_active_document_ids(collection_name)
        collection = self._get_collection(collection_name)

        # ChromaDB query
        kwargs: dict = {"query_texts": [query], "n_results": top_k * 2}
        if filters:
            kwargs["where"] = filters
        try:
            raw = collection.query(**kwargs)
        except Exception as e:
            logger.error(f"ChromaDB query failed: {e}")
            return []

        if not raw["ids"] or not raw["ids"][0]:
            return []

        results: list[SearchResult] = []
        ids = raw["ids"][0]
        docs = raw["documents"][0]
        metas = raw["metadatas"][0]
        dists = raw["distances"][0]

        for i, chunk_id in enumerate(ids):
            meta = metas[i] or {}
            doc_id = meta.get("document_id", "")
            # 过滤已删除文档
            if doc_id not in active_ids:
                continue
            score = self._distance_to_score(dists[i])
            if score < score_threshold:
                continue
            results.append(SearchResult(
                document_id=doc_id,
                chunk_id=chunk_id,
                text=docs[i],
                score=score,
                metadata=meta,
                source_title=meta.get("source_title", ""),
                chunk_index=meta.get("chunk_index", 0),
            ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    async def hybrid_search(
        self,
        query: str,
        keyword: str,
        top_k: int = 5,
        collection_name: str = "avatar_knowledge",
        filters: dict | None = None,
        score_threshold: float = 0.0,
    ) -> list[SearchResult]:
        """
        混合搜索：semantic candidate ∩ keyword hit。
        query 用于语义检索，keyword 用于文本匹配过滤，两者独立。
        """
        candidates = await self.semantic_search(
            query=query,
            top_k=top_k * 2,
            collection_name=collection_name,
            filters=filters,
            score_threshold=score_threshold,
        )
        keyword_lower = keyword.lower()
        filtered = [r for r in candidates if keyword_lower in r.text.lower()]
        return filtered[:top_k]

    def merge_passages(
        self,
        results: list[SearchResult],
        max_gap: int = 2,
    ) -> list[PassageResult]:
        """同文档 chunk 合并为 passage。"""
        from collections import defaultdict
        by_doc: dict[str, list[SearchResult]] = defaultdict(list)
        for r in results:
            by_doc[r.document_id].append(r)

        passages: list[PassageResult] = []
        for doc_id, chunks in by_doc.items():
            chunks.sort(key=lambda c: c.chunk_index)
            groups: list[list[SearchResult]] = [[chunks[0]]]
            for c in chunks[1:]:
                last = groups[-1][-1]
                if c.chunk_index - last.chunk_index <= max_gap:
                    groups[-1].append(c)
                else:
                    groups.append([c])

            for group in groups:
                passages.append(PassageResult(
                    document_id=doc_id,
                    source_title=group[0].source_title,
                    text="\n".join(c.text for c in group),
                    score=max(c.score for c in group),
                    chunk_ids=[c.chunk_id for c in group],
                    chunk_indices=[c.chunk_index for c in group],
                ))

        passages.sort(key=lambda p: p.score, reverse=True)
        return passages
