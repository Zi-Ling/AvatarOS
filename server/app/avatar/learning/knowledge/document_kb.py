# avatar/learning/knowledge/document_kb.py
"""
Document Knowledge Base (文档知识库)

这是一个 Learning 模块，提供文档管理和 RAG 功能。
它使用 Memory 层的 Vector Store 作为底层存储，但业务逻辑在这里。

设计原则：
1. 业务逻辑层（不是存储层）
2. 使用 Memory 的 Vector Store（复用底层能力）
3. 独立的 ChromaDB Collection（不与 Episodic 混合）
4. 易于扩展（未来可加 PDF、DOCX）
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..base import LearningModule

# 使用统一的 ChromaDB 管理器
from app.avatar.infra.vectorstore import get_chroma_manager, CHROMADB_AVAILABLE


class Document:
    """文档数据结构"""
    def __init__(
        self,
        name: str,
        content: str,
        doc_type: str = "txt",
        metadata: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None,
    ):
        self.name = name
        self.content = content
        self.doc_type = doc_type
        self.metadata = metadata or {}
        self.created_at = created_at or datetime.utcnow()
        self.id = self._generate_id()
    
    def _generate_id(self) -> str:
        """生成文档唯一 ID"""
        unique_str = f"{self.name}:{self.created_at.isoformat()}"
        return hashlib.md5(unique_str.encode()).hexdigest()


class DocumentKnowledgeBase(LearningModule):
    """
    文档知识库：Learning 层的业务模块
    
    功能：
    1. 上传文档（TXT/MD）
    2. 自动分块和索引
    3. 语义检索（RAG）
    4. 列出所有文档
    5. 删除文档
    
    扩展性：
    - 未来可以加 PDF 解析（pdfplumber）
    - 未来可以加 DOCX 解析（python-docx）
    - 未来可以加更复杂的分块策略
    
    架构说明：
    - 这是 Learning 模块，不是 Memory 模块
    - 使用独立的 ChromaDB Collection（"documents"）
    - 不与 Memory 的 Episodic/Knowledge 混合
    """
    
    name: str = "document_kb"
    description: str = "Document Knowledge Base for RAG (Retrieval-Augmented Generation)"
    
    def __init__(self, persist_directory: str | Path):
        """
        初始化文档知识库
        
        Args:
            persist_directory: ChromaDB 持久化目录
        """
        if not CHROMADB_AVAILABLE:
            raise ImportError("ChromaDB is not installed. Install it with: pip install chromadb")
        
        self._persist_dir = Path(persist_directory)
        
        # 使用统一的 ChromaDB 管理器获取 Persistent Client
        chroma_manager = get_chroma_manager()
        self._client = chroma_manager.get_persistent_client(self._persist_dir)
        
        if self._client is None:
            raise RuntimeError(
                f"Failed to initialize ChromaDB Persistent Client at {self._persist_dir}"
            )
        
        # 创建独立的 documents Collection
        self._collection = chroma_manager.get_or_create_collection(
            client=self._client,
            name="documents",
            metadata={"hnsw:space": "cosine"}
        )
        
        if self._collection is None:
            raise RuntimeError(
                "Failed to create or get collection 'documents'"
            )
    
    # -------------------------------------------------------------------------
    # LearningModule 接口实现
    # -------------------------------------------------------------------------
    def learn(self, example, *, ctx) -> Any:
        """
        实现 LearningModule 的 learn 方法
        
        文档知识库不需要从任务/技能事件中学习，
        而是通过 add_document 方法主动添加文档。
        
        这个方法是为了满足 LearningModule 接口要求。
        """
        from ..base import LearningResult
        return LearningResult(
            success=True,
            message="DocumentKB does not learn from task/skill events",
            data=None,
        )
    
    # -------------------------------------------------------------------------
    # 文档管理功能
    # -------------------------------------------------------------------------
    def _chunk_document(self, content: str, chunk_size: int = 500) -> List[str]:
        """
        文档分块策略（简单实现，保持扩展性）
        
        当前策略：按段落分割
        未来可以扩展：
        - 按语义分割
        - 按句子分割
        - 重叠分块
        """
        # 按双换行符分割段落
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        
        chunks = []
        current_chunk = ""
        
        for para in paragraphs:
            # 如果当前块 + 新段落超过 chunk_size，保存当前块
            if len(current_chunk) + len(para) > chunk_size and current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = para
            else:
                current_chunk += "\n\n" + para if current_chunk else para
        
        # 保存最后一块
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        return chunks if chunks else [content]  # 至少返回一块
    
    def add_document(self, document: Document) -> Dict[str, Any]:
        """
        添加文档并索引
        
        Returns:
            {"doc_id": str, "chunks_count": int}
        """
        # 分块
        chunks = self._chunk_document(document.content)
        
        # 为每个块生成 ID 和 metadata
        chunk_ids = []
        chunk_docs = []
        chunk_metas = []
        
        for i, chunk in enumerate(chunks):
            chunk_id = f"{document.id}_chunk_{i}"
            chunk_ids.append(chunk_id)
            chunk_docs.append(chunk)
            chunk_metas.append({
                "doc_id": document.id,
                "doc_name": document.name,
                "doc_type": document.doc_type,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "created_at": document.created_at.isoformat(),
                **document.metadata,
            })
        
        # 保存到 ChromaDB
        self._collection.upsert(
            ids=chunk_ids,
            documents=chunk_docs,
            metadatas=chunk_metas,
        )
        
        return {
            "doc_id": document.id,
            "chunks_count": len(chunks),
        }
    
    def search(self, query: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """
        语义搜索文档（RAG 核心功能）
        
        Args:
            query: 查询文本
            n_results: 返回结果数量
        
        Returns:
            匹配的文档块列表
        """
        if not query.strip():
            return []
        
        results = self._collection.query(
            query_texts=[query],
            n_results=n_results,
        )
        
        matches = []
        if results["ids"] and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                matches.append({
                    "chunk_id": results["ids"][0][i],
                    "content": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i] if results.get("distances") else None,
                })
        
        return matches
    
    def list_documents(self) -> List[Dict[str, Any]]:
        """
        列出所有文档（按文档聚合）
        
        Returns:
            [{"id": str, "name": str, "type": str, "chunks": int, "created_at": str}, ...]
        """
        # 获取所有记录
        all_data = self._collection.get()
        
        if not all_data["ids"]:
            return []
        
        # 按文档 ID 聚合
        docs_map = {}
        for i, meta in enumerate(all_data["metadatas"]):
            doc_id = meta.get("doc_id")
            if doc_id not in docs_map:
                docs_map[doc_id] = {
                    "id": doc_id,
                    "name": meta.get("doc_name", "Unknown"),
                    "type": meta.get("doc_type", "txt"),
                    "chunks": 0,
                    "created_at": meta.get("created_at", ""),
                }
            docs_map[doc_id]["chunks"] += 1
        
        # 转换为列表并排序（最新的在前）
        docs_list = list(docs_map.values())
        docs_list.sort(key=lambda x: x["created_at"], reverse=True)
        
        return docs_list
    
    def delete_document(self, doc_id: str) -> int:
        """
        删除文档（删除所有相关的块）
        
        Returns:
            删除的块数量
        """
        # 查询该文档的所有块
        results = self._collection.get(
            where={"doc_id": doc_id}
        )
        
        if results["ids"]:
            # 删除所有块
            self._collection.delete(ids=results["ids"])
            return len(results["ids"])
        
        return 0
    
    def get_document_content(self, doc_id: str) -> Optional[str]:
        """
        获取文档的完整内容（合并所有块）
        """
        results = self._collection.get(
            where={"doc_id": doc_id}
        )
        
        if not results["ids"]:
            return None
        
        # 按 chunk_index 排序
        chunks = []
        for i, meta in enumerate(results["metadatas"]):
            chunks.append({
                "index": meta.get("chunk_index", 0),
                "content": results["documents"][i],
            })
        
        chunks.sort(key=lambda x: x["index"])
        
        return "\n\n".join(c["content"] for c in chunks)
    
    def count(self) -> int:
        """返回文档总数"""
        docs = self.list_documents()
        return len(docs)
    
    # -------------------------------------------------------------------------
    # RAG 功能：为 Planner 提供上下文增强
    # -------------------------------------------------------------------------
    def get_relevant_context(self, query: str, max_chunks: int = 3) -> str:
        """
        为给定查询获取相关文档上下文（用于 RAG）
        
        Args:
            query: 用户查询
            max_chunks: 最多返回多少个文档块
        
        Returns:
            拼接后的上下文文本
        """
        matches = self.search(query, n_results=max_chunks)
        
        if not matches:
            return ""
        
        context_parts = []
        for i, match in enumerate(matches, 1):
            doc_name = match["metadata"].get("doc_name", "Unknown")
            content = match["content"]
            context_parts.append(f"[文档 {i}: {doc_name}]\n{content}")
        
        return "\n\n---\n\n".join(context_parts)

