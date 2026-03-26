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
    modifications: Optional[dict] = None  # 编辑后批准时附带的修改内容


class ApprovalStatusResponse(BaseModel):
    """审批状态响应"""
    request_id: str
    status: str
    message: str
    operation: str
    expires_at: Optional[str] = None
    responded_at: Optional[str] = None
    user_comment: Optional[str] = None
    task_id: Optional[str] = None
    step_id: Optional[str] = None
    details: Optional[dict] = None


@router.get("/history")
async def get_approval_history(
    status: Optional[str] = None,   # pending / approved / rejected / expired
    task_id: Optional[str] = None,
    limit: int = 50,
):
    """
    查询历史审批记录（持久化，不依赖内存状态）。
    支持按 status / task_id 过滤，按创建时间倒序。
    """
    try:
        from sqlmodel import Session, select
        from app.db.database import engine
        from app.db.system import ApprovalRequest

        with Session(engine) as session:
            stmt = select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc()).limit(limit)
            if status:
                stmt = stmt.where(ApprovalRequest.status == status)
            if task_id:
                stmt = stmt.where(ApprovalRequest.task_id == task_id)
            records = session.exec(stmt).all()

        return {
            "count": len(records),
            "records": [
                {
                    "request_id": r.request_id,
                    "status": r.status,
                    "message": r.message,
                    "operation": r.operation,
                    "task_id": r.task_id,
                    "step_id": r.step_id,
                    "details": r.details,
                    "user_comment": r.user_comment,
                    "interrupt_type": r.interrupt_type,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                    "responded_at": r.responded_at.isoformat() if r.responded_at else None,
                }
                for r in records
            ],
        }

    except Exception as e:
        logger.error(f"Failed to get approval history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
            user_comment=request.user_comment,
            modifications=request.modifications,
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
            expires_at=request_data.get('expires_at'),
            responded_at=request_data.get('responded_at'),
            user_comment=request_data.get('user_comment'),
            task_id=request_data.get('task_id'),
            step_id=request_data.get('step_id'),
            details=request_data.get('details'),
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
    """
    try:
        from sqlmodel import Session, select
        from app.db.database import engine
        from app.db.system import ApprovalRequest
        from datetime import datetime, timezone

        service = get_approval_service()
        service.cleanup_expired()

        with Session(engine) as session:
            stmt = select(ApprovalRequest).where(
                ApprovalRequest.status == ApprovalStatus.PENDING.value
            ).order_by(ApprovalRequest.created_at.desc())
            reqs = session.exec(stmt).all()
            pending = [
                {
                    "request_id": r.request_id,
                    "message": r.message,
                    "operation": r.operation,
                    "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                    "task_id": r.task_id,
                    "step_id": r.step_id,
                    "details": r.details,
                    "interrupt_type": r.interrupt_type,
                }
                for r in reqs
            ]

        return {"success": True, "count": len(pending), "requests": pending}

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
