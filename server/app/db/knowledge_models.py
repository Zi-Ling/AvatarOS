# app/db/knowledge_models.py
"""知识库文档索引元数据模型"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import SQLModel, Field


class KnowledgeDocumentRecord(SQLModel, table=True):
    """
    知识库文档索引元数据。
    业务状态管理在 SQLite，ChromaDB 只存 chunk 内容和 embedding。
    """

    __tablename__ = "knowledge_documents"

    id: str = Field(primary_key=True)  # UUID
    title: str = Field(index=False)
    source_path: str = Field(default="")
    content_hash: str = Field(index=True)  # SHA-256
    file_format: str = Field(default="txt")  # txt / md / pdf / json
    collection_name: str = Field(default="avatar_knowledge", index=True)
    chunk_count: int = Field(default=0)
    chunk_config_json: str = Field(default="{}")  # {"strategy","window_size","overlap"}
    # pending / indexing / indexed / failed / permanently_failed
    index_status: str = Field(default="pending", index=True)
    is_deleted: bool = Field(default=False, index=True)
    deleted_at: Optional[datetime] = Field(default=None)
    failure_count: int = Field(default=0)
    failure_reason: Optional[str] = Field(default=None)
    tags_json: Optional[str] = Field(default=None)  # JSON array
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    indexed_at: Optional[datetime] = Field(default=None)
