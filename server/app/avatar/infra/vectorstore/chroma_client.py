# app/infra/chroma_client.py
"""
统一的 ChromaDB 客户端管理器

负责管理所有 ChromaDB 实例，避免实例冲突和资源泄漏。

架构设计：
- Ephemeral Client：用于纯内存的临时索引（如 Artifact 搜索）
- Persistent Client：用于持久化的向量存储（如 Episodic Memory、Document KB）
"""

from __future__ import annotations
import logging
from typing import Optional, Any
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import chromadb
    from chromadb.config import Settings
    from chromadb.api.client import Client
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    chromadb = None
    Settings = None
    Client = None


class ChromaDBManager:
    """
    ChromaDB 客户端管理器（单例模式）
    
    功能：
    1. 管理 Ephemeral Client（内存实例）
    2. 管理 Persistent Client（持久化实例）
    3. 提供统一的 Collection 创建接口
    4. 避免实例冲突和资源泄漏
    """
    
    _instance: Optional[ChromaDBManager] = None
    _ephemeral_client: Optional[Any] = None
    _persistent_clients: dict[str, Any] = {}  # path -> client
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not CHROMADB_AVAILABLE:
            logger.warning("ChromaDB not available. Vector search features will be disabled.")
    
    def get_ephemeral_client(self) -> Optional[Any]:
        """
        获取 Ephemeral Client（单例，纯内存）
        
        用途：
        - ArtifactSearcher（Artifact 语义搜索）
        - 其他不需要持久化的临时索引
        
        Returns:
            ChromaDB EphemeralClient 实例，如果不可用则返回 None
        """
        if not CHROMADB_AVAILABLE:
            return None
        
        if self._ephemeral_client is None:
            try:
                self._ephemeral_client = chromadb.EphemeralClient(
                    settings=Settings(
                        anonymized_telemetry=False,
                        allow_reset=True,
                    )
                )
                logger.info("ChromaDBManager: Created Ephemeral Client")
            except Exception as e:
                logger.error(f"ChromaDBManager: Failed to create Ephemeral Client: {e}")
                return None
        
        return self._ephemeral_client
    
    def get_persistent_client(self, persist_directory: str | Path) -> Optional[Any]:
        """
        获取 Persistent Client（持久化到磁盘）
        
        用途：
        - ChromaVectorStore（Episodic Memory）
        - DocumentKnowledgeBase（文档知识库）
        
        Args:
            persist_directory: 持久化目录路径
        
        Returns:
            ChromaDB PersistentClient 实例，如果不可用则返回 None
        """
        if not CHROMADB_AVAILABLE:
            return None
        
        # 规范化路径
        persist_dir = Path(persist_directory).resolve()
        persist_dir_str = str(persist_dir)
        
        # 如果已经存在，直接返回
        if persist_dir_str in self._persistent_clients:
            return self._persistent_clients[persist_dir_str]
        
        # 创建新的 Persistent Client
        try:
            persist_dir.mkdir(parents=True, exist_ok=True)
            
            client = chromadb.PersistentClient(
                path=str(persist_dir),
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=True,
                )
            )
            
            self._persistent_clients[persist_dir_str] = client
            logger.info(f"ChromaDBManager: Created Persistent Client at {persist_dir}")
            
            return client
            
        except Exception as e:
            logger.error(f"ChromaDBManager: Failed to create Persistent Client at {persist_dir}: {e}")
            return None
    
    def get_or_create_collection(
        self,
        client: Any,
        name: str,
        metadata: Optional[dict] = None
    ) -> Optional[Any]:
        """
        获取或创建 Collection
        
        Args:
            client: ChromaDB Client 实例
            name: Collection 名称
            metadata: Collection 元数据（可选）
        
        Returns:
            Collection 实例，如果失败则返回 None
        """
        if client is None:
            return None
        
        try:
            collection = client.get_or_create_collection(
                name=name,
                metadata=metadata or {}
            )
            logger.debug(f"ChromaDBManager: Got or created collection '{name}'")
            return collection
            
        except Exception as e:
            logger.error(f"ChromaDBManager: Failed to get or create collection '{name}': {e}")
            return None
    
    def reset(self):
        """
        重置所有客户端（主要用于测试）
        """
        if self._ephemeral_client is not None:
            try:
                self._ephemeral_client.reset()
            except Exception as e:
                logger.warning(f"ChromaDBManager: Failed to reset Ephemeral Client: {e}")
        
        self._ephemeral_client = None
        self._persistent_clients.clear()
        logger.info("ChromaDBManager: Reset all clients")
    
    def get_stats(self) -> dict[str, Any]:
        """
        获取管理器统计信息
        
        Returns:
            统计信息字典
        """
        return {
            "chromadb_available": CHROMADB_AVAILABLE,
            "ephemeral_client_initialized": self._ephemeral_client is not None,
            "persistent_clients_count": len(self._persistent_clients),
            "persistent_client_paths": list(self._persistent_clients.keys()),
        }


# 全局单例
_chroma_manager: Optional[ChromaDBManager] = None


def get_chroma_manager() -> ChromaDBManager:
    """
    获取全局 ChromaDB 管理器实例
    
    Returns:
        ChromaDBManager 单例
    """
    global _chroma_manager
    if _chroma_manager is None:
        _chroma_manager = ChromaDBManager()
    return _chroma_manager

