# avatar/memory/vector/store.py
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..base import MemoryKind, MemoryRecord

# 使用统一的 ChromaDB 管理器
from app.avatar.infra.vectorstore import get_chroma_manager, CHROMADB_AVAILABLE

import logging

logger = logging.getLogger(__name__)


class ChromaVectorStore:
    """
    基于 ChromaDB 的向量存储：
    - 用于语义检索 Episodic Memory（历史任务、失败案例等）
    - 支持相似度搜索，找到历史上类似的任务
    
    使用场景：
    1. Planner 规划时，检索相似的成功案例作为参考（RAG）
    2. 错误诊断时，检索相似的失败案例及解决方案
    3. 用户提问时，检索相似的历史对话
    """

    def __init__(self, persist_directory: str | Path, collection_name: str = "episodic_memory") -> None:
        """
        初始化 ChromaDB 向量存储
        
        Args:
            persist_directory: 向量数据库持久化目录
            collection_name: Collection 名称（默认 "episodic_memory"）
        """
        if not CHROMADB_AVAILABLE:
            raise ImportError(
                "ChromaDB is not installed. Install it with: pip install chromadb"
            )
        
        self._persist_dir = Path(persist_directory)
        self._collection_name = collection_name
        
        # 使用统一的 ChromaDB 管理器获取 Persistent Client
        chroma_manager = get_chroma_manager()
        self._client = chroma_manager.get_persistent_client(self._persist_dir)
        
        if self._client is None:
            raise RuntimeError(
                f"Failed to initialize ChromaDB Persistent Client at {self._persist_dir}"
            )
        
        # 获取或创建 Collection
        self._collection = chroma_manager.get_or_create_collection(
            client=self._client,
            name=collection_name,
            metadata={"hnsw:space": "cosine"}  # 使用余弦相似度
        )
        
        if self._collection is None:
            raise RuntimeError(
                f"Failed to create or get collection '{collection_name}'"
            )
    
    def _generate_id(self, record: MemoryRecord) -> str:
        """
        为 MemoryRecord 生成唯一 ID
        使用 key + created_at 的 hash
        """
        unique_str = f"{record.key}:{record.created_at.isoformat()}"
        return hashlib.md5(unique_str.encode()).hexdigest()
    
    def _record_to_document(self, record: MemoryRecord) -> str:
        """
        将 MemoryRecord 转换为可索引的文本
        
        这是语义检索的关键：提取有意义的文本内容
        """
        data = record.data
        
        # 根据不同的 key 前缀提取不同的内容
        if record.key.startswith("task:"):
            # 任务记录：提取 summary + 用户请求
            summary = data.get("summary", "")
            user_request = data.get("extra", {}).get("user_request", "")
            steps_desc = self._extract_steps_description(data.get("extra", {}).get("steps", []))
            return f"{user_request}\n{summary}\n{steps_desc}".strip()
        
        elif record.key.startswith("skill:"):
            # 技能事件：提取技能名称 + 详情
            skill_name = data.get("skill_name", "")
            detail = data.get("detail", "")
            return f"{skill_name}: {detail}".strip()
        
        else:
            # 默认：尝试提取所有字符串字段
            text_parts = []
            for value in data.values():
                if isinstance(value, str) and value:
                    text_parts.append(value)
            return " ".join(text_parts).strip()
    
    def _extract_steps_description(self, steps: List[Dict[str, Any]]) -> str:
        """从步骤列表中提取可读描述"""
        if not steps:
            return ""
        
        descriptions = []
        try:
            for step in steps:
                if isinstance(step, dict):
                    skill = step.get("skill", "") or step.get("skill_name", "")
                    desc = step.get("description", "")
                    
                    # 确保是字符串类型
                    skill_str = str(skill) if skill and not str(skill).startswith('_') else ""
                    desc_str = str(desc) if desc and not str(desc).startswith('_') else ""
                    
                    if desc_str:
                        descriptions.append(f"{skill_str}: {desc_str}")
                    elif skill_str:
                        descriptions.append(skill_str)
        except Exception as e:
            logger.warning(f"Error extracting steps description: {e}")
            return ""
        
        return " → ".join(descriptions)
    
    def save(self, record: MemoryRecord) -> None:
        """
        保存一条记录到向量数据库
        
        Args:
            record: MemoryRecord（只接受 EPISODIC 类型）
        """
        if record.kind != MemoryKind.EPISODIC:
            # 只索引 Episodic Memory（事件记录）
            return
        
        try:
            doc_id = self._generate_id(record)
            document = self._record_to_document(record)
            
            if not document or not document.strip():
                # 如果没有可索引的内容，跳过
                return
        except Exception as e:
            # 文档生成失败，记录但不影响主流程
            logger.warning(f"Failed to generate document from record: {e}")
            return
        
        # 准备 metadata（用于过滤）
        # ChromaDB 要求 metadata 值必须是基本类型（str, int, float, bool）
        metadata = {
            "kind": str(record.kind.value) if hasattr(record.kind, 'value') else str(record.kind),
            "key": str(record.key),
            "created_at": record.created_at.isoformat(),
        }
        
        # 添加一些额外的过滤字段（确保类型安全）
        if record.key.startswith("task:"):
            metadata["source"] = "task"
            # 安全地获取 status，确保是字符串
            status = record.data.get("status", "unknown")
            metadata["status"] = str(status) if status is not None else "unknown"
        elif record.key.startswith("skill:"):
            metadata["source"] = "skill"
            # 安全地获取 skill_name，确保是字符串
            skill_name = record.data.get("skill_name", "")
            metadata["skill_name"] = str(skill_name) if skill_name is not None else ""
        
        # 保存到 ChromaDB
        try:
            self._collection.upsert(
                ids=[doc_id],
                documents=[document],
                metadatas=[metadata]
            )
        except Exception as e:
            # 详细的错误信息用于调试
            logger.warning(f"ChromaDB upsert failed: {e}, doc_len={len(document)}, id={doc_id}")
            # 不抛出异常，允许主流程继续
    
    def semantic_search(
        self,
        query: str,
        n_results: int = 5,
        filter_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        语义搜索：根据查询文本找到最相似的记录
        
        Args:
            query: 查询文本（例如用户的新任务描述）
            n_results: 返回结果数量
            filter_metadata: 元数据过滤条件（例如 {"source": "task", "status": "success"}）
        
        Returns:
            相似记录列表，每个包含：
            - id: 记录 ID
            - document: 索引的文本
            - metadata: 元数据
            - distance: 距离（越小越相似）
        """
        if not query.strip():
            return []
        
        # 执行查询
        results = self._collection.query(
            query_texts=[query],
            n_results=n_results,
            where=filter_metadata if filter_metadata else None,
        )
        
        # 转换结果格式
        matches = []
        if results["ids"] and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                matches.append({
                    "id": results["ids"][0][i],
                    "document": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i] if results.get("distances") else None,
                })
        
        return matches
    
    def get_similar_tasks(
        self,
        task_description: str,
        status: Optional[str] = None,
        n_results: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        查找相似的历史任务
        
        Args:
            task_description: 任务描述（用户的新请求）
            status: 过滤状态（"success" 或 "failed"，None 表示不过滤）
            n_results: 返回数量
        
        Returns:
            相似任务列表
        """
        filter_dict = {"source": "task"}
        if status:
            filter_dict["status"] = status
        
        return self.semantic_search(
            query=task_description,
            n_results=n_results,
            filter_metadata=filter_dict,
        )
    
    def count(self) -> int:
        """返回 Collection 中的记录总数"""
        return self._collection.count()
    
    def reset(self) -> None:
        """清空 Collection（危险操作，仅用于测试）"""
        self._client.delete_collection(self._collection.name)
        self._collection = self._client.get_or_create_collection(
            name=self._collection.name,
            metadata={"hnsw:space": "cosine"}
        )

