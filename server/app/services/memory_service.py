# server/app/services/memory_service.py

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

from app.core.config import AVATAR_MEMORY_DIR

# 向量库路径
MEMORY_DB_PATH = AVATAR_MEMORY_DIR


class MemoryService:
    """
    长期记忆管理服务
    
    使用 ChromaDB 向量库存储和检索长期记忆。
    适用场景：
    - 用户偏好和习惯
    - 历史对话摘要
    - 知识库和文档
    - 跨会话的上下文
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or MEMORY_DB_PATH
        self.client = None
        self.collection = None
        self._init_db()
    
    def _init_db(self):
        """初始化 ChromaDB"""
        try:
            import chromadb
            from chromadb.config import Settings
            
            self.db_path.mkdir(parents=True, exist_ok=True)
            
            self.client = chromadb.PersistentClient(
                path=str(self.db_path),
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=True
                )
            )
            
            # 获取或创建默认集合
            self.collection = self.client.get_or_create_collection(
                name="avatar_memory",
                metadata={"description": "Long-term memory storage"}
            )
            
            logger.info(f"Memory database initialized at {self.db_path}")
        
        except ImportError:
            logger.error("ChromaDB not installed. Run: pip install chromadb")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize memory database: {e}")
            raise
    
    def store(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        memory_id: Optional[str] = None
    ) -> str:
        """
        存储记忆
        
        Args:
            content: 记忆内容（会被向量化）
            metadata: 元数据（用于过滤和检索）
            memory_id: 记忆ID（如果不提供则自动生成）
        
        Returns:
            记忆ID
        """
        try:
            if not memory_id:
                memory_id = f"mem_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
            
            # 添加时间戳到元数据
            meta = metadata or {}
            meta["created_at"] = datetime.now().isoformat()
            
            self.collection.add(
                documents=[content],
                metadatas=[meta],
                ids=[memory_id]
            )
            
            logger.debug(f"Memory stored: {memory_id}")
            return memory_id
        
        except Exception as e:
            logger.error(f"Failed to store memory: {e}")
            raise
    
    def search(
        self,
        query: str,
        limit: int = 5,
        filter_metadata: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        搜索记忆
        
        Args:
            query: 查询文本
            limit: 返回数量限制
            filter_metadata: 元数据过滤条件
        
        Returns:
            记忆列表，每个包含：
            - id: 记忆ID
            - content: 记忆内容
            - metadata: 元数据
            - distance: 相似度距离（越小越相似）
        """
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=limit,
                where=filter_metadata
            )
            
            memories = []
            if results and results['ids'] and len(results['ids']) > 0:
                ids = results['ids'][0]
                documents = results['documents'][0]
                metadatas = results['metadatas'][0]
                distances = results['distances'][0]
                
                for i in range(len(ids)):
                    memories.append({
                        "id": ids[i],
                        "content": documents[i],
                        "metadata": metadatas[i],
                        "distance": distances[i]
                    })
            
            logger.debug(f"Memory search: found {len(memories)} results")
            return memories
        
        except Exception as e:
            logger.error(f"Failed to search memory: {e}")
            return []
    
    def delete(self, memory_id: str) -> bool:
        """删除记忆"""
        try:
            self.collection.delete(ids=[memory_id])
            logger.debug(f"Memory deleted: {memory_id}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to delete memory: {e}")
            return False
    
    def get(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """获取指定记忆"""
        try:
            result = self.collection.get(ids=[memory_id])
            
            if result and result['ids'] and len(result['ids']) > 0:
                return {
                    "id": result['ids'][0],
                    "content": result['documents'][0],
                    "metadata": result['metadatas'][0]
                }
            
            return None
        
        except Exception as e:
            logger.error(f"Failed to get memory: {e}")
            return None
    
    def clear_all(self) -> bool:
        """清空所有记忆（危险操作）"""
        try:
            self.client.delete_collection("avatar_memory")
            self.collection = self.client.create_collection(
                name="avatar_memory",
                metadata={"description": "Long-term memory storage"}
            )
            logger.warning("All memories cleared")
            return True
        
        except Exception as e:
            logger.error(f"Failed to clear memories: {e}")
            return False


# 全局单例
_memory_service: Optional[MemoryService] = None


def get_memory_service() -> MemoryService:
    """获取全局 MemoryService 实例"""
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService()
    return _memory_service
