# app/services/knowledge/rag_context.py
"""RAG 上下文构建器 — 搜索 → 合并 → 多样性控制 → token budget → source_refs"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.services.knowledge.search_service import KnowledgeSearchService, PassageResult

logger = logging.getLogger(__name__)


@dataclass
class SourceRef:
    document_id: str
    chunk_id: str
    source_title: str
    chunk_index: int
    score: float


@dataclass
class RAGContext:
    context_text: str
    source_refs: list[SourceRef] = field(default_factory=list)
    total_chars: int = 0
    documents_used: int = 0


class RAGContextBuilder:
    def __init__(
        self,
        search_service: KnowledgeSearchService,
        max_context_chars: int = 4000,
        max_chunks_per_doc: int = 3,
    ):
        self._search = search_service
        self._max_chars = max_context_chars
        self._max_per_doc = max_chunks_per_doc

    async def build_context(
        self,
        query: str,
        top_k: int = 10,
        collection_name: str = "avatar_knowledge",
        filters: dict | None = None,
    ) -> RAGContext:
        """
        构建 RAG 上下文：
        1. semantic_search(top_k)
        2. merge_passages 合并同文档相邻 chunk
        3. 文档多样性控制：单文档最多 max_chunks_per_doc 段 passage
        4. 按 token budget 裁剪
        5. 生成 source_refs
        """
        results = await self._search.semantic_search(
            query=query, top_k=top_k, collection_name=collection_name, filters=filters,
        )
        if not results:
            return RAGContext(context_text="", source_refs=[], total_chars=0, documents_used=0)

        passages = self._search.merge_passages(results)

        # 多样性控制 + token budget 裁剪
        doc_count: dict[str, int] = {}
        selected: list[PassageResult] = []
        total = 0

        for p in passages:  # already sorted by score desc
            cur = doc_count.get(p.document_id, 0)
            if cur >= self._max_per_doc:
                continue
            if total + len(p.text) > self._max_chars:
                continue
            selected.append(p)
            doc_count[p.document_id] = cur + 1
            total += len(p.text)

        # 拼接 context_text + 生成 source_refs
        texts: list[str] = []
        refs: list[SourceRef] = []
        doc_ids_used: set[str] = set()

        for p in selected:
            texts.append(p.text)
            doc_ids_used.add(p.document_id)
            for cid, cidx in zip(p.chunk_ids, p.chunk_indices):
                refs.append(SourceRef(
                    document_id=p.document_id,
                    chunk_id=cid,
                    source_title=p.source_title,
                    chunk_index=cidx,
                    score=p.score,
                ))

        context_text = "\n\n".join(texts)
        return RAGContext(
            context_text=context_text,
            source_refs=refs,
            total_chars=len(context_text),
            documents_used=len(doc_ids_used),
        )
