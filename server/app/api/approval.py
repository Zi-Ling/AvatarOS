# server/app/api/approval.py
"""
审批 API 路由
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.approval_service import get_approval_service, ApprovalStatus

router = APIRouter(prefix="/api/approval", tags=["approval"])
logger = logging.getLogger(__name__)


class ApprovalRespondRequest(BaseModel):
    """审批响应请求"""
    request_id: str
    approved: bool
    user_comment: Optional[str] = None


class ApprovalStatusResponse(BaseModel):
    """审批状态响应"""
    request_id: str
    status: str
    message: str
    operation: str
    created_at: str
    expires_at: str
    responded_at: Optional[str] = None
    user_comment: Optional[str] = None


@router.post("/respond")
async def respond_to_approval(request: ApprovalRespondRequest):
    """
    响应审批请求
    
    Args:
        request: 审批响应请求
    
    Returns:
        成功响应
    """
    try:
        service = get_approval_service()
        success = service.respond(
            request_id=request.request_id,
            approved=request.approved,
            user_comment=request.user_comment
        )
        
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Approval request not found or already responded: {request.request_id}"
            )
        
        return {
            "success": True,
            "request_id": request.request_id,
            "approved": request.approved
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to respond to approval: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{request_id}", response_model=ApprovalStatusResponse)
async def get_approval_status(request_id: str):
    """
    获取审批请求状态
    
    Args:
        request_id: 请求ID
    
    Returns:
        审批状态
    """
    try:
        service = get_approval_service()
        request_data = service.get_request(request_id)
        
        if not request_data:
            raise HTTPException(
                status_code=404,
                detail=f"Approval request not found: {request_id}"
            )
        
        return ApprovalStatusResponse(
            request_id=request_data['request_id'],
            status=request_data['status'],
            message=request_data['message'],
            operation=request_data['operation'],
            created_at=request_data['created_at'],
            expires_at=request_data['expires_at'],
            responded_at=request_data.get('responded_at'),
            user_comment=request_data.get('user_comment')
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get approval status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pending")
async def get_pending_approvals():
    """
    获取所有待审批请求
    
    Returns:
        待审批请求列表
    """
    try:
        service = get_approval_service()
        
        # 先清理过期请求
        service.cleanup_expired()
        
        # 获取所有 pending 请求
        with service._get_conn() as conn:
            rows = conn.execute("""
                SELECT request_id, message, operation, created_at, expires_at
                FROM approval_requests
                WHERE status = ?
                ORDER BY created_at DESC
            """, (ApprovalStatus.PENDING.value,)).fetchall()
            
            pending = [dict(row) for row in rows]
        
        return {
            "success": True,
            "count": len(pending),
            "requests": pending
        }
    
    except Exception as e:
        logger.error(f"Failed to get pending approvals: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cleanup")
async def cleanup_expired_approvals():
    """
    清理过期的审批请求
    
    Returns:
        清理数量
    """
    try:
        service = get_approval_service()
        count = service.cleanup_expired()
        
        return {
            "success": True,
            "cleaned_count": count
        }
    
    except Exception as e:
        logger.error(f"Failed to cleanup expired approvals: {e}")
        raise HTTPException(status_code=500, detail=str(e))
