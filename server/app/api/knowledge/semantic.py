# app/api/knowledge/semantic.py
"""知识库语义搜索 API 端点"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/knowledge", tags=["knowledge-semantic"])
logger = logging.getLogger(__name__)


# ── Request / Response Models ──

class SemanticSearchRequest(BaseModel):
    query: str
    top_k: int = Field(5, ge=1, le=100)
    collection: str = "avatar_knowledge"
    filters: Optional[dict] = None
    score_threshold: float = Field(0.0, ge=0.0, le=1.0)
    search_mode: str = Field("semantic", pattern="^(semantic|hybrid)$")
    keyword: Optional[str] = None


class SearchResultItem(BaseModel):
    document_id: str
    chunk_id: str
    text: str
    score: float
    source_title: str
    chunk_index: int


class SemanticSearchResponse(BaseModel):
    results: list[SearchResultItem]
    source_refs: list[dict]
    total_count: int


class IndexRequest(BaseModel):
    document_path: Optional[str] = None
    document_content: Optional[str] = None
    title: str
    file_format: str = Field("txt", pattern="^(txt|md|pdf|json)$")
    collection: str = "avatar_knowledge"
    tags: Optional[list[str]] = None


class IndexResponse(BaseModel):
    document_id: str
    chunk_count: int
    index_status: str


class IndexStatusResponse(BaseModel):
    documents: list[dict]
    total_count: int


class CleanupResponse(BaseModel):
    cleaned_count: int


# ── Endpoints ──

@router.post("/semantic-search", response_model=SemanticSearchResponse)
async def semantic_search(req: SemanticSearchRequest):
    """语义搜索 / 混合搜索"""
    from app.services.knowledge import get_knowledge_search_service
    svc = get_knowledge_search_service()

    try:
        if req.search_mode == "hybrid":
            if not req.keyword:
                raise HTTPException(400, "hybrid 模式需要提供 keyword 参数")
            results = await svc.hybrid_search(
                query=req.query, keyword=req.keyword,
                top_k=req.top_k, collection_name=req.collection,
                filters=req.filters, score_threshold=req.score_threshold,
            )
        else:
            results = await svc.semantic_search(
                query=req.query, top_k=req.top_k,
                collection_name=req.collection, filters=req.filters,
                score_threshold=req.score_threshold,
            )

        items = [
            SearchResultItem(
                document_id=r.document_id, chunk_id=r.chunk_id,
                text=r.text, score=r.score,
                source_title=r.source_title, chunk_index=r.chunk_index,
            )
            for r in results
        ]
        refs = [
            {"document_id": r.document_id, "chunk_id": r.chunk_id,
             "source_title": r.source_title, "score": r.score}
            for r in results
        ]
        return SemanticSearchResponse(results=items, source_refs=refs, total_count=len(items))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Semantic search failed: {e}")
        raise HTTPException(500, str(e))


@router.post("/index", response_model=IndexResponse)
async def index_document(req: IndexRequest):
    """索引文档到知识库"""
    import uuid
    from app.services.knowledge import get_knowledge_index_service

    if not req.document_path and not req.document_content:
        raise HTTPException(400, "需要提供 document_path 或 document_content")

    content: str | bytes
    if req.document_content:
        content = req.document_content
    else:
        try:
            mode = "rb" if req.file_format == "pdf" else "r"
            with open(req.document_path, mode) as f:
                content = f.read()
        except Exception as e:
            raise HTTPException(400, f"读取文件失败: {e}")

    svc = get_knowledge_index_service()
    try:
        doc_id = str(uuid.uuid4())
        record = await svc.index_document(
            document_id=doc_id, content=content,
            title=req.title, file_format=req.file_format,
            collection_name=req.collection, tags=req.tags,
        )
        return IndexResponse(
            document_id=record.id,
            chunk_count=record.chunk_count,
            index_status=record.index_status,
        )
    except Exception as e:
        logger.error(f"Index failed: {e}")
        raise HTTPException(500, str(e))


@router.post("/documents/{document_id}/reindex", response_model=IndexResponse)
async def reindex_document(document_id: str):
    """重新索引文档"""
    from app.services.knowledge import get_knowledge_index_service
    svc = get_knowledge_index_service()
    try:
        record = await svc.reindex_document(document_id)
        return IndexResponse(
            document_id=record.id,
            chunk_count=record.chunk_count,
            index_status=record.index_status,
        )
    except Exception as e:
        logger.error(f"Reindex failed: {e}")
        raise HTTPException(500, str(e))


@router.delete("/documents/{document_id}/index")
async def delete_document_index(document_id: str):
    """删除文档索引（软删除）"""
    from app.services.knowledge import get_knowledge_index_service
    svc = get_knowledge_index_service()
    try:
        await svc.delete_document_index(document_id)
        return {"success": True, "document_id": document_id}
    except Exception as e:
        logger.error(f"Delete index failed: {e}")
        raise HTTPException(500, str(e))


@router.get("/index-status", response_model=IndexStatusResponse)
async def get_index_status(
    status: Optional[str] = None,
    collection: str = "avatar_knowledge",
):
    """查询索引状态"""
    from app.services.knowledge.doc_store import KnowledgeDocumentStore
    store = KnowledgeDocumentStore()
    try:
        if status:
            records = store.list_by_status(status)
        else:
            records = store.list_by_collection(collection)
        docs = [
            {
                "id": r.id, "title": r.title,
                "index_status": r.index_status,
                "chunk_count": r.chunk_count,
                "collection_name": r.collection_name,
                "is_deleted": r.is_deleted,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in records
        ]
        return IndexStatusResponse(documents=docs, total_count=len(docs))
    except Exception as e:
        logger.error(f"Index status query failed: {e}")
        raise HTTPException(500, str(e))


@router.post("/cleanup-orphans", response_model=CleanupResponse)
async def cleanup_orphans(collection: str = "avatar_knowledge"):
    """清理孤立 chunk"""
    from app.services.knowledge import get_knowledge_index_service
    svc = get_knowledge_index_service()
    try:
        count = await svc.cleanup_orphan_chunks(collection)
        return CleanupResponse(cleaned_count=count)
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        raise HTTPException(500, str(e))
