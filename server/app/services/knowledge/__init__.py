# app/services/knowledge/__init__.py
"""知识库语义层服务 — 单例工厂函数"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.knowledge.index_service import KnowledgeIndexService
    from app.services.knowledge.search_service import KnowledgeSearchService
    from app.services.knowledge.rag_context import RAGContextBuilder

_index_service: KnowledgeIndexService | None = None
_search_service: KnowledgeSearchService | None = None
_rag_builder: RAGContextBuilder | None = None


def _get_chroma_client():
    """与 MemoryService 共享同一个 ChromaDB PersistentClient 实例。"""
    from app.services.memory_service import get_memory_service
    return get_memory_service().client


def get_knowledge_index_service() -> KnowledgeIndexService:
    global _index_service
    if _index_service is None:
        from app.services.knowledge.index_service import KnowledgeIndexService
        from app.services.knowledge.preprocessor import DocumentPreprocessor
        from app.services.knowledge.chunker import Chunker
        from app.services.knowledge.doc_store import KnowledgeDocumentStore

        _index_service = KnowledgeIndexService(
            chroma_client=_get_chroma_client(),
            preprocessor=DocumentPreprocessor(),
            chunker=Chunker(),
            doc_store=KnowledgeDocumentStore(),
        )
    return _index_service


def get_knowledge_search_service() -> KnowledgeSearchService:
    global _search_service
    if _search_service is None:
        from app.services.knowledge.search_service import KnowledgeSearchService
        from app.services.knowledge.doc_store import KnowledgeDocumentStore

        _search_service = KnowledgeSearchService(
            chroma_client=_get_chroma_client(),
            doc_store=KnowledgeDocumentStore(),
        )
    return _search_service


def get_rag_context_builder() -> RAGContextBuilder:
    global _rag_builder
    if _rag_builder is None:
        from app.services.knowledge.rag_context import RAGContextBuilder

        _rag_builder = RAGContextBuilder(
            search_service=get_knowledge_search_service(),
        )
    return _rag_builder
