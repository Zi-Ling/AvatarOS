# app/services/knowledge/index_service.py
"""知识库索引服务 — 文档索引流水线"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from app.db.knowledge_models import KnowledgeDocumentRecord
from app.services.knowledge.chunker import Chunker, ChunkConfig
from app.services.knowledge.doc_store import KnowledgeDocumentStore
from app.services.knowledge.preprocessor import DocumentPreprocessor, PreprocessError

logger = logging.getLogger(__name__)

_MAX_RETRY = 3


class KnowledgeIndexService:
    """文档索引流水线：预处理 → 分块 → 写入 ChromaDB"""

    def __init__(
        self,
        chroma_client,
        preprocessor: DocumentPreprocessor,
        chunker: Chunker,
        doc_store: KnowledgeDocumentStore,
    ):
        self._client = chroma_client
        self._preprocessor = preprocessor
        self._chunker = chunker
        self._doc_store = doc_store

    def _get_collection(self, name: str = "avatar_knowledge"):
        return self._client.get_or_create_collection(name=name)

    @staticmethod
    def _content_hash(content: str | bytes) -> str:
        if isinstance(content, str):
            content = content.encode("utf-8")
        return hashlib.sha256(content).hexdigest()

    async def index_document(
        self,
        document_id: str,
        content: str | bytes,
        title: str,
        file_format: str = "txt",
        collection_name: str = "avatar_knowledge",
        tags: list[str] | None = None,
    ) -> KnowledgeDocumentRecord:
        """
        完整索引流水线。content_hash 相同时跳过重建（整文重建策略）。
        """
        c_hash = self._content_hash(content)

        # 检查是否已存在且内容未变
        existing = self._doc_store.get_by_id(document_id)
        if existing and existing.content_hash == c_hash and existing.index_status == "indexed":
            return existing

        # 创建或更新 record
        now = datetime.now(timezone.utc)
        config = self._chunker.config
        config_snap = json.dumps({
            "strategy": config.strategy,
            "window_size": config.window_size,
            "overlap": config.overlap,
        })

        if existing:
            existing.index_status = "indexing"
            existing.content_hash = c_hash
            existing.title = title
            existing.file_format = file_format
            existing.collection_name = collection_name
            existing.chunk_config_json = config_snap
            existing.tags_json = json.dumps(tags) if tags else None
            existing.updated_at = now
            record = self._doc_store.update(existing)
        else:
            record = KnowledgeDocumentRecord(
                id=document_id,
                title=title,
                content_hash=c_hash,
                file_format=file_format,
                collection_name=collection_name,
                chunk_config_json=config_snap,
                index_status="indexing",
                tags_json=json.dumps(tags) if tags else None,
                created_at=now,
                updated_at=now,
            )
            record = self._doc_store.create(record)

        try:
            # 删除旧 chunk（整文重建）
            collection = self._get_collection(collection_name)
            self._delete_chunks(collection, document_id)

            # 预处理 → 分块
            text = self._preprocessor.preprocess(content, file_format)
            chunks = self._chunker.chunk(text, document_id)

            if chunks:
                ids = [c.chunk_id for c in chunks]
                documents = [c.text for c in chunks]
                metadatas = [
                    {
                        "document_id": document_id,
                        "chunk_index": c.chunk_index,
                        "start_offset": c.start_offset,
                        "end_offset": c.end_offset,
                        "source_title": title,
                        "collection_name": collection_name,
                        "tags": ",".join(tags) if tags else "",
                    }
                    for c in chunks
                ]
                collection.add(ids=ids, documents=documents, metadatas=metadatas)

            # 更新 record 为 indexed
            record.index_status = "indexed"
            record.chunk_count = len(chunks)
            record.indexed_at = datetime.now(timezone.utc)
            record.failure_reason = None
            record = self._doc_store.update(record)
            return record

        except Exception as e:
            record.index_status = "failed"
            record.failure_count = (record.failure_count or 0) + 1
            record.failure_reason = str(e)[:500]
            self._doc_store.update(record)
            raise

    async def reindex_document(self, document_id: str) -> KnowledgeDocumentRecord:
        """重新索引：读取现有 record 信息，强制重建。"""
        record = self._doc_store.get_by_id(document_id)
        if record is None:
            raise ValueError(f"Document {document_id} not found")
        # 强制重建：将 content_hash 置空使 index_document 不跳过
        record.content_hash = ""
        self._doc_store.update(record)
        # 调用方需要提供 content，这里只做状态重置
        record.index_status = "pending"
        return self._doc_store.update(record)

    async def delete_document_index(self, document_id: str) -> None:
        """
        两阶段删除：
        1. is_deleted=True（业务层立即不可见）
        2. 删除 ChromaDB chunk
        不物理删除 record。
        """
        record = self._doc_store.get_by_id(document_id)
        if record is None:
            return
        # 阶段 1：软删除
        record.is_deleted = True
        record.deleted_at = datetime.now(timezone.utc)
        record.index_status = "pending"
        self._doc_store.update(record)

        # 阶段 2：清理 ChromaDB chunk
        try:
            collection = self._get_collection(record.collection_name)
            self._delete_chunks(collection, document_id)
        except Exception as e:
            logger.warning(
                f"Failed to delete chunks for {document_id}, "
                f"orphan cleanup will handle: {e}"
            )

    async def retry_failed(self, document_id: str) -> KnowledgeDocumentRecord:
        """重试失败的索引。failure_count >= 3 标记 permanently_failed。"""
        record = self._doc_store.get_by_id(document_id)
        if record is None:
            raise ValueError(f"Document {document_id} not found")
        if record.index_status not in ("failed",):
            raise ValueError(f"Document {document_id} is not in failed state")
        if (record.failure_count or 0) >= _MAX_RETRY:
            record.index_status = "permanently_failed"
            return self._doc_store.update(record)
        record.index_status = "pending"
        return self._doc_store.update(record)

    async def cleanup_orphan_chunks(
        self, collection_name: str = "avatar_knowledge"
    ) -> int:
        """清理孤立 chunk：ChromaDB 中存在但 record 已删除或不存在的 chunk。"""
        collection = self._get_collection(collection_name)
        all_data = collection.get()
        if not all_data["ids"]:
            return 0

        active_ids = self._doc_store.get_active_document_ids(collection_name)
        orphan_ids: list[str] = []
        for chunk_id in all_data["ids"]:
            doc_id = chunk_id.split("__chunk_")[0] if "__chunk_" in chunk_id else chunk_id
            if doc_id not in active_ids:
                orphan_ids.append(chunk_id)

        if orphan_ids:
            collection.delete(ids=orphan_ids)
        return len(orphan_ids)

    def _delete_chunks(self, collection, document_id: str):
        """删除指定文档的所有 chunk。"""
        all_data = collection.get(where={"document_id": document_id})
        if all_data["ids"]:
            collection.delete(ids=all_data["ids"])
