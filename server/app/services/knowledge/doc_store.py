# app/services/knowledge/doc_store.py
"""KnowledgeDocumentRecord CRUD 封装"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from app.db.knowledge_models import KnowledgeDocumentRecord

logger = logging.getLogger(__name__)


class KnowledgeDocumentStore:
    """封装 KnowledgeDocumentRecord 的 CRUD 操作。"""

    def __init__(self, session_factory):
        """
        Args:
            session_factory: 返回 Session 上下文管理器的可调用对象。
                             例如 lambda: Session(engine)
        """
        self._session_factory = session_factory

    def _session(self) -> Session:
        return self._session_factory()

    def create(self, record: KnowledgeDocumentRecord) -> KnowledgeDocumentRecord:
        with self._session() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def get_by_id(self, document_id: str) -> Optional[KnowledgeDocumentRecord]:
        with self._session() as session:
            return session.get(KnowledgeDocumentRecord, document_id)

    def update(self, record: KnowledgeDocumentRecord) -> KnowledgeDocumentRecord:
        with self._session() as session:
            existing = session.get(KnowledgeDocumentRecord, record.id)
            if existing is None:
                raise ValueError(f"Document {record.id} not found")
            for key, value in record.model_dump(exclude_unset=False).items():
                setattr(existing, key, value)
            existing.updated_at = datetime.now(timezone.utc)
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return existing

    def delete(self, document_id: str) -> bool:
        with self._session() as session:
            record = session.get(KnowledgeDocumentRecord, document_id)
            if record is None:
                return False
            session.delete(record)
            session.commit()
            return True

    def list_by_status(
        self, status: str, collection_name: Optional[str] = None
    ) -> list[KnowledgeDocumentRecord]:
        with self._session() as session:
            stmt = select(KnowledgeDocumentRecord).where(
                KnowledgeDocumentRecord.index_status == status,
                KnowledgeDocumentRecord.is_deleted == False,  # noqa: E712
            )
            if collection_name:
                stmt = stmt.where(
                    KnowledgeDocumentRecord.collection_name == collection_name
                )
            return list(session.exec(stmt).all())

    def list_by_collection(
        self, collection_name: str, include_deleted: bool = False
    ) -> list[KnowledgeDocumentRecord]:
        with self._session() as session:
            stmt = select(KnowledgeDocumentRecord).where(
                KnowledgeDocumentRecord.collection_name == collection_name
            )
            if not include_deleted:
                stmt = stmt.where(
                    KnowledgeDocumentRecord.is_deleted == False  # noqa: E712
                )
            return list(session.exec(stmt).all())

    def get_active_document_ids(
        self, collection_name: str = "avatar_knowledge"
    ) -> set[str]:
        """返回未删除的文档 ID 集合，用于搜索时过滤。"""
        with self._session() as session:
            stmt = select(KnowledgeDocumentRecord.id).where(
                KnowledgeDocumentRecord.collection_name == collection_name,
                KnowledgeDocumentRecord.is_deleted == False,  # noqa: E712
            )
            return set(session.exec(stmt).all())
