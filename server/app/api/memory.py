# server/app/api/memory.py
"""
记忆管理 API 路由
"""
import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.memory_service import get_memory_service

router = APIRouter(prefix="/api/memory", tags=["memory"])
logger = logging.getLogger(__name__)


class MemoryStoreRequest(BaseModel):
    """存储记忆请求"""
    content: str
    metadata: Optional[Dict[str, Any]] = None
    memory_id: Optional[str] = None


class MemorySearchRequest(BaseModel):
    """搜索记忆请求"""
    query: str
    limit: int = 5
    filter_metadata: Optional[Dict[str, Any]] = None


class MemoryDeleteRequest(BaseModel):
    """删除记忆请求"""
    memory_ids: List[str]


@router.post("/store")
async def store_memory(request: MemoryStoreRequest):
    """
    存储记忆到向量库
    
    Args:
        request: 记忆存储请求
    
    Returns:
        记忆ID
    """
    try:
        service = get_memory_service()
        memory_id = service.store(
            content=request.content,
            metadata=request.metadata,
            memory_id=request.memory_id
        )
        
        return {
            "success": True,
            "memory_id": memory_id
        }
    
    except Exception as e:
        logger.error(f"Failed to store memory: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search")
async def search_memory(request: MemorySearchRequest):
    """
    搜索记忆（语义相似度）
    
    Args:
        request: 记忆搜索请求
    
    Returns:
        搜索结果列表
    """
    try:
        service = get_memory_service()
        results = service.search(
            query=request.query,
            limit=request.limit,
            filter_metadata=request.filter_metadata
        )
        
        return {
            "success": True,
            "count": len(results),
            "results": results
        }
    
    except Exception as e:
        logger.error(f"Failed to search memory: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/delete")
async def delete_memory(request: MemoryDeleteRequest):
    """
    删除记忆
    
    Args:
        request: 记忆删除请求
    
    Returns:
        成功响应
    """
    try:
        service = get_memory_service()
        success = service.delete(memory_ids=request.memory_ids)
        
        return {
            "success": success,
            "deleted_count": len(request.memory_ids)
        }
    
    except Exception as e:
        logger.error(f"Failed to delete memory: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_memory_stats():
    """
    获取记忆库统计信息
    
    Returns:
        统计信息
    """
    try:
        service = get_memory_service()
        
        # 获取记忆总数
        collection = service.collection
        count = collection.count()
        
        return {
            "success": True,
            "total_memories": count,
            "collection_name": service.collection_name
        }
    
    except Exception as e:
        logger.error(f"Failed to get memory stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list")
async def list_memories(limit: int = 20, offset: int = 0):
    """
    列出记忆（分页）
    
    Args:
        limit: 每页数量
        offset: 偏移量
    
    Returns:
        记忆列表
    """
    try:
        service = get_memory_service()
        collection = service.collection
        
        # ChromaDB 的 get 方法获取所有记忆
        result = collection.get(
            limit=limit,
            offset=offset,
            include=["documents", "metadatas"]
        )
        
        memories = []
        if result and result.get('ids'):
            for i, memory_id in enumerate(result['ids']):
                memories.append({
                    "memory_id": memory_id,
                    "content": result['documents'][i] if result.get('documents') else None,
                    "metadata": result['metadatas'][i] if result.get('metadatas') else None
                })
        
        return {
            "success": True,
            "count": len(memories),
            "memories": memories
        }
    
    except Exception as e:
        logger.error(f"Failed to list memories: {e}")
        raise HTTPException(status_code=500, detail=str(e))
