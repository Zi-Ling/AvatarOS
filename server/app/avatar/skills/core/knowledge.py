# app/avatar/skills/core/knowledge.py
"""Knowledge Skills — 知识库语义搜索与文档入库"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import Field

from ..base import BaseSkill, SkillSpec, SideEffect, SkillRiskLevel
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext

logger = logging.getLogger(__name__)


# ── knowledge.search ──

class KnowledgeSearchInput(SkillInput):
    query: str = Field(..., description="搜索查询文本")
    top_k: int = Field(5, description="返回结果数量")
    collection: str = Field("avatar_knowledge", description="ChromaDB collection 名称")
    filters: Optional[dict] = Field(None, description="ChromaDB where 过滤条件")
    score_threshold: float = Field(0.0, description="最低 score 阈值 (0-1)")
    search_mode: str = Field("semantic", description="搜索模式: semantic / hybrid")
    keyword: Optional[str] = Field(None, description="hybrid 模式的关键词过滤文本")


class KnowledgeSearchOutput(SkillOutput):
    results: list[dict] = Field(default_factory=list, description="搜索结果列表")
    source_refs: list[dict] = Field(default_factory=list, description="引用来源")
    total_count: int = Field(0, description="结果总数")


@register_skill
class KnowledgeSearchSkill(BaseSkill[KnowledgeSearchInput, KnowledgeSearchOutput]):
    spec = SkillSpec(
        name="knowledge.search",
        description="Search the knowledge base using semantic or hybrid mode. "
                    "语义搜索知识库，支持 semantic / hybrid 模式。",
        input_model=KnowledgeSearchInput,
        output_model=KnowledgeSearchOutput,
        side_effects={SideEffect.DATA_READ},
        risk_level=SkillRiskLevel.READ,
        aliases=["knowledge_search", "search_knowledge", "kb_search"],
        tags=["knowledge", "search", "semantic", "知识库", "搜索", "语义"],
    )

    async def run(self, ctx: SkillContext, params: KnowledgeSearchInput) -> KnowledgeSearchOutput:
        if ctx.dry_run:
            return KnowledgeSearchOutput(success=True, message="[dry_run] Would search knowledge base")

        from app.services.knowledge import get_knowledge_search_service
        svc = get_knowledge_search_service()

        try:
            if params.search_mode == "hybrid":
                if not params.keyword:
                    return KnowledgeSearchOutput(
                        success=False, message="hybrid 模式需要提供 keyword 参数",
                    )
                results = await svc.hybrid_search(
                    query=params.query, keyword=params.keyword,
                    top_k=params.top_k, collection_name=params.collection,
                    filters=params.filters, score_threshold=params.score_threshold,
                )
            else:
                results = await svc.semantic_search(
                    query=params.query, top_k=params.top_k,
                    collection_name=params.collection, filters=params.filters,
                    score_threshold=params.score_threshold,
                )

            result_dicts = [
                {
                    "document_id": r.document_id,
                    "chunk_id": r.chunk_id,
                    "text": r.text,
                    "score": r.score,
                    "source_title": r.source_title,
                    "chunk_index": r.chunk_index,
                }
                for r in results
            ]
            source_refs = [
                {"document_id": r.document_id, "chunk_id": r.chunk_id,
                 "source_title": r.source_title, "score": r.score}
                for r in results
            ]
            return KnowledgeSearchOutput(
                success=True, message="搜索完成",
                results=result_dicts, source_refs=source_refs,
                total_count=len(results),
            )
        except Exception as e:
            logger.error(f"Knowledge search failed: {e}")
            return KnowledgeSearchOutput(success=False, message=str(e))


# ── knowledge.ingest ──

class KnowledgeIngestInput(SkillInput):
    document_path: Optional[str] = Field(None, description="文档文件路径")
    document_content: Optional[str] = Field(None, description="文档内容（与 document_path 二选一）")
    title: str = Field(..., description="文档标题")
    file_format: str = Field("txt", description="文件格式: txt / md / pdf / json")
    collection: str = Field("avatar_knowledge", description="ChromaDB collection 名称")
    tags: Optional[list[str]] = Field(None, description="文档标签列表")


class KnowledgeIngestOutput(SkillOutput):
    document_id: str = Field("", description="文档 ID")
    chunk_count: int = Field(0, description="分块数量")
    index_status: str = Field("", description="索引状态")


@register_skill
class KnowledgeIngestSkill(BaseSkill[KnowledgeIngestInput, KnowledgeIngestOutput]):
    spec = SkillSpec(
        name="knowledge.ingest",
        description="Index a document into the knowledge base for semantic search. "
                    "将文档索引到知识库，支持 txt/md/pdf/json 格式。",
        input_model=KnowledgeIngestInput,
        output_model=KnowledgeIngestOutput,
        side_effects={SideEffect.DATA_WRITE},
        risk_level=SkillRiskLevel.WRITE,
        aliases=["knowledge_ingest", "ingest_document", "kb_ingest"],
        tags=["knowledge", "ingest", "index", "知识库", "入库", "索引"],
    )

    async def run(self, ctx: SkillContext, params: KnowledgeIngestInput) -> KnowledgeIngestOutput:
        if ctx.dry_run:
            return KnowledgeIngestOutput(success=True, message="[dry_run] Would ingest document")

        import uuid

        content: str | bytes | None = None
        if params.document_content:
            content = params.document_content
        elif params.document_path:
            try:
                mode = "rb" if params.file_format == "pdf" else "r"
                with open(params.document_path, mode) as f:
                    content = f.read()
            except Exception as e:
                return KnowledgeIngestOutput(
                    success=False, message=f"读取文件失败: {e}",
                )
        else:
            return KnowledgeIngestOutput(
                success=False, message="需要提供 document_path 或 document_content",
            )

        from app.services.knowledge import get_knowledge_index_service
        svc = get_knowledge_index_service()

        try:
            doc_id = str(uuid.uuid4())
            record = await svc.index_document(
                document_id=doc_id, content=content,
                title=params.title, file_format=params.file_format,
                collection_name=params.collection, tags=params.tags,
            )
            return KnowledgeIngestOutput(
                success=True, message="文档索引成功",
                document_id=record.id,
                chunk_count=record.chunk_count,
                index_status=record.index_status,
            )
        except Exception as e:
            logger.error(f"Knowledge ingest failed: {e}")
            return KnowledgeIngestOutput(success=False, message=str(e))
