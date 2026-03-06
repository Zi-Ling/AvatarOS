# server/app/api/state.py
"""
状态管理 API 路由
"""
import logging
from typing import Optional, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.state_service import get_state_service

router = APIRouter(prefix="/api/state", tags=["state"])
logger = logging.getLogger(__name__)


class StateSetRequest(BaseModel):
    """设置状态请求"""
    scope: str  # task | session | user
    scope_id: str
    key: str
    value: Any
    ttl_seconds: Optional[int] = None


class StateGetRequest(BaseModel):
    """获取状态请求"""
    scope: str
    scope_id: str
    key: str
    default: Optional[Any] = None


class StateDeleteRequest(BaseModel):
    """删除状态请求"""
    scope: str
    scope_id: str
    key: str


@router.post("/set")
async def set_state(request: StateSetRequest):
    """
    设置状态
    
    Args:
        request: 状态设置请求
    
    Returns:
        成功响应
    """
    try:
        service = get_state_service()
        service.set(
            scope=request.scope,
            scope_id=request.scope_id,
            key=request.key,
            value=request.value,
            ttl_seconds=request.ttl_seconds
        )
        
        return {
            "success": True,
            "scope": request.scope,
            "scope_id": request.scope_id,
            "key": request.key
        }
    
    except Exception as e:
        logger.error(f"Failed to set state: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/get")
async def get_state(request: StateGetRequest):
    """
    获取状态
    
    Args:
        request: 状态获取请求
    
    Returns:
        状态值
    """
    try:
        service = get_state_service()
        value = service.get(
            scope=request.scope,
            scope_id=request.scope_id,
            key=request.key,
            default=request.default
        )
        
        return {
            "success": True,
            "scope": request.scope,
            "scope_id": request.scope_id,
            "key": request.key,
            "value": value
        }
    
    except Exception as e:
        logger.error(f"Failed to get state: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/delete")
async def delete_state(request: StateDeleteRequest):
    """
    删除状态
    
    Args:
        request: 状态删除请求
    
    Returns:
        成功响应
    """
    try:
        service = get_state_service()
        success = service.delete(
            scope=request.scope,
            scope_id=request.scope_id,
            key=request.key
        )
        
        return {
            "success": success,
            "scope": request.scope,
            "scope_id": request.scope_id,
            "key": request.key
        }
    
    except Exception as e:
        logger.error(f"Failed to delete state: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list/{scope}/{scope_id}")
async def list_state_keys(scope: str, scope_id: str):
    """
    列出指定 scope 下的所有 key
    
    Args:
        scope: 作用域类型
        scope_id: 作用域ID
    
    Returns:
        key 列表
    """
    try:
        service = get_state_service()
        
        with service._get_conn() as conn:
            rows = conn.execute("""
                SELECT key, created_at, updated_at, expires_at
                FROM state
                WHERE scope = ? AND scope_id = ?
                ORDER BY updated_at DESC
            """, (scope, scope_id)).fetchall()
            
            keys = [dict(row) for row in rows]
        
        return {
            "success": True,
            "scope": scope,
            "scope_id": scope_id,
            "count": len(keys),
            "keys": keys
        }
    
    except Exception as e:
        logger.error(f"Failed to list state keys: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cleanup")
async def cleanup_expired_state():
    """
    清理过期的状态
    
    Returns:
        清理数量
    """
    try:
        service = get_state_service()
        count = service.cleanup_expired()
        
        return {
            "success": True,
            "cleaned_count": count
        }
    
    except Exception as e:
        logger.error(f"Failed to cleanup expired state: {e}")
        raise HTTPException(status_code=500, detail=str(e))
