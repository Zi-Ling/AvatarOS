# avatar/artifact/search.py
"""
Artifact 语义搜索

提供基于向量的 Artifact 检索功能
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import time

logger = logging.getLogger(__name__)

# 使用统一的 ChromaDB 管理器
from app.avatar.infra.vectorstore import get_chroma_manager, CHROMADB_AVAILABLE


@dataclass
class ScoredArtifact:
    """带分数的 Artifact 搜索结果"""
    artifact: Dict[str, Any]
    score: float  # 相似度分数（0-1，越大越相似）
    distance: float  # 原始距离
    match_reason: str  # 匹配原因


class ArtifactSearcher:
    """
    Artifact 语义搜索器
    
    功能：
    - 向量化 Artifacts 的元数据和内容
    - 语义搜索最相关的 Artifacts
    - 多维过滤（时间、类型、会话）
    """
    
    def __init__(self):
        self._collection: Optional[Any] = None
        self._index_ready = False
        self._indexed_ids = set()  # 跟踪已索引的 artifact IDs
        
        if CHROMADB_AVAILABLE:
            try:
                # 使用统一的 ChromaDB 管理器获取 Ephemeral Client
                chroma_manager = get_chroma_manager()
                client = chroma_manager.get_ephemeral_client()
                
                if client is not None:
                    # 创建或获取 collection
                    self._collection = chroma_manager.get_or_create_collection(
                        client=client,
                        name="artifacts",
                        metadata={"description": "Artifact semantic search index"}
                    )
                    
                    if self._collection is not None:
                        self._index_ready = True
                        logger.info("ArtifactSearcher: Initialized with ChromaDB (via ChromaDBManager)")
                    else:
                        logger.warning("ArtifactSearcher: Failed to create collection")
                else:
                    logger.warning("ArtifactSearcher: Failed to get Ephemeral Client from ChromaDBManager")
                
            except Exception as e:
                logger.warning(f"ArtifactSearcher: Failed to initialize ChromaDB: {e}")
        else:
            logger.warning("ArtifactSearcher: ChromaDB not available, search will be disabled")
    
    def index_artifact(self, artifact: Dict[str, Any]) -> bool:
        """
        索引单个 Artifact
        
        参数:
            artifact: Artifact 对象
        
        返回:
            是否成功索引
        """
        if not self._index_ready:
            return False
        
        try:
            artifact_id = artifact.get("id")
            if not artifact_id:
                logger.warning("ArtifactSearcher: Artifact missing ID, skipping")
                return False
            
            # 如果已索引，跳过
            if artifact_id in self._indexed_ids:
                return True
            
            # 构建文档内容（用于向量化）
            meta = artifact.get("meta", {})
            artifact_type = artifact.get("type", "")
            uri = artifact.get("uri", "")
            
            # 组合多个字段作为文档内容
            doc_parts = []
            
            # 文件名
            if "filename" in meta:
                doc_parts.append(meta["filename"])
            
            # 类型
            if artifact_type:
                doc_parts.append(f"type:{artifact_type}")
            
            # 描述
            if "description" in meta:
                doc_parts.append(meta["description"])
            
            # 创建技能
            if "skill" in meta:
                doc_parts.append(f"created_by:{meta['skill']}")
            
            # 标签
            if "tags" in meta:
                tags = meta["tags"]
                if isinstance(tags, list):
                    doc_parts.extend(tags)
            
            # URI（只取文件名部分）
            if uri:
                filename = uri.split("/")[-1]
                doc_parts.append(filename)
            
            document = " ".join(doc_parts)
            
            if not document.strip():
                document = "artifact"  # 默认内容
            
            # 准备元数据
            metadata = {
                "type": artifact_type[:50] if artifact_type else "unknown",  # ChromaDB 限制长度
                "uri": uri[:200] if uri else "",
                "session_id": meta.get("session_id", "")[:50],
                "created_at": str(meta.get("created_at", 0))
            }
            
            # 添加到索引
            self._collection.add(
                ids=[artifact_id],
                documents=[document],
                metadatas=[metadata]
            )
            
            self._indexed_ids.add(artifact_id)
            logger.debug(f"ArtifactSearcher: Indexed artifact {artifact_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"ArtifactSearcher: Failed to index artifact: {e}")
            return False
    
    def search(
        self,
        query: str,
        session_id: Optional[str] = None,
        artifact_type: Optional[str] = None,
        limit: int = 10
    ) -> List[ScoredArtifact]:
        """
        语义搜索 Artifacts
        
        参数:
            query: 搜索查询
            session_id: 限制会话（可选）
            artifact_type: 限制类型（可选）
            limit: 返回数量
        
        返回:
            带分数的搜索结果列表
        """
        if not self._index_ready:
            logger.warning("ArtifactSearcher: Index not ready")
            return []
        
        if not query or not query.strip():
            return []
        
        try:
            # 构建查询条件
            where = None
            if session_id and artifact_type:
                where = {
                    "$and": [
                        {"session_id": {"$eq": session_id}},
                        {"type": {"$eq": artifact_type}}
                    ]
                }
            elif session_id:
                where = {"session_id": {"$eq": session_id}}
            elif artifact_type:
                where = {"type": {"$eq": artifact_type}}
            
            # 执行查询
            results = self._collection.query(
                query_texts=[query],
                n_results=min(limit, 100),
                where=where if where else None
            )
            
            if not results or not results['ids'] or not results['ids'][0]:
                return []
            
            # 解析结果
            ids = results['ids'][0]
            distances = results['distances'][0] if 'distances' in results else [0.0] * len(ids)
            metadatas = results['metadatas'][0] if 'metadatas' in results else [{}] * len(ids)
            
            scored_artifacts = []
            for artifact_id, distance, metadata in zip(ids, distances, metadatas):
                # 转换距离为相似度分数
                similarity = 1.0 / (1.0 + distance)
                
                # 重构 artifact 对象
                artifact = {
                    "id": artifact_id,
                    "type": metadata.get("type", ""),
                    "uri": metadata.get("uri", ""),
                    "meta": {
                        "session_id": metadata.get("session_id", ""),
                        "created_at": float(metadata.get("created_at", 0))
                    }
                }
                
                scored_artifacts.append(ScoredArtifact(
                    artifact=artifact,
                    score=similarity,
                    distance=distance,
                    match_reason="semantic_match"
                ))
            
            logger.debug(f"ArtifactSearcher: Found {len(scored_artifacts)} results for '{query}'")
            
            return scored_artifacts
            
        except Exception as e:
            logger.error(f"ArtifactSearcher: Search failed: {e}")
            return []
    
    def get_stats(self) -> Dict[str, Any]:
        """获取索引统计信息"""
        if not self._index_ready:
            return {"status": "not_ready"}
        
        try:
            count = self._collection.count()
            return {
                "status": "ready",
                "total_artifacts": count,
                "indexed_ids": len(self._indexed_ids)
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}


# 全局单例
_artifact_searcher: Optional[ArtifactSearcher] = None


def get_artifact_searcher() -> ArtifactSearcher:
    """获取全局 ArtifactSearcher 实例"""
    global _artifact_searcher
    if _artifact_searcher is None:
        _artifact_searcher = ArtifactSearcher()
    return _artifact_searcher

