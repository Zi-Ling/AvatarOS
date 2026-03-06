# server/app/services/approval_service.py

from __future__ import annotations

import json
import sqlite3
import logging
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from contextlib import contextmanager
from enum import Enum

logger = logging.getLogger(__name__)

# 审批数据库路径
APPROVAL_DB_PATH = Path.home() / ".avatarOS" / "approval.db"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    TIMEOUT = "timeout"


class ApprovalService:
    """
    人工审批服务（幂等协议）
    
    使用 request_id 实现幂等性：
    - 相同 request_id 的请求只会创建一次
    - 支持超时自动拒绝
    - 支持异步等待审批结果
    """
    
    def __init__(self, db_path: Optional[Path] = None, default_timeout: int = 60):
        self.db_path = db_path or APPROVAL_DB_PATH
        self.default_timeout = default_timeout
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._init_db()
    
    def _init_db(self):
        """初始化数据库表"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS approval_requests (
                    request_id TEXT PRIMARY KEY,
                    task_id TEXT,
                    step_id TEXT,
                    message TEXT,
                    operation TEXT,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    status TEXT,
                    user_comment TEXT,
                    responded_at TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status ON approval_requests(status)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_expires_at ON approval_requests(expires_at)
            """)
            
            conn.commit()
            logger.info(f"Approval database initialized at {self.db_path}")
    
    @contextmanager
    def _get_conn(self):
        """获取数据库连接"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def create_request(
        self,
        request_id: str,
        message: str,
        operation: str,
        task_id: Optional[str] = None,
        step_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        timeout_seconds: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        创建审批请求（幂等）
        
        Args:
            request_id: 请求ID（幂等键）
            message: 审批消息
            operation: 操作类型
            task_id: 任务ID
            step_id: 步骤ID
            details: 详细信息
            timeout_seconds: 超时时间（秒）
        
        Returns:
            请求信息字典
        """
        try:
            # 检查是否已存在（幂等性）
            existing = self.get_request(request_id)
            if existing:
                logger.debug(f"Approval request already exists: {request_id}")
                return existing
            
            timeout = timeout_seconds or self.default_timeout
            expires_at = (datetime.now() + timedelta(seconds=timeout)).isoformat()
            details_json = json.dumps(details, ensure_ascii=False) if details else None
            
            with self._get_conn() as conn:
                conn.execute("""
                    INSERT INTO approval_requests (
                        request_id, task_id, step_id, message, operation,
                        details, expires_at, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    request_id, task_id, step_id, message, operation,
                    details_json, expires_at, ApprovalStatus.PENDING.value
                ))
                
                conn.commit()
            
            logger.info(f"Approval request created: {request_id}")
            
            return {
                "request_id": request_id,
                "message": message,
                "operation": operation,
                "status": ApprovalStatus.PENDING.value,
                "expires_at": expires_at
            }
        
        except Exception as e:
            logger.error(f"Failed to create approval request: {e}")
            raise
    
    def get_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        """获取审批请求"""
        try:
            with self._get_conn() as conn:
                row = conn.execute("""
                    SELECT * FROM approval_requests
                    WHERE request_id = ?
                """, (request_id,)).fetchone()
                
                if not row:
                    return None
                
                request = dict(row)
                if request.get('details'):
                    request['details'] = json.loads(request['details'])
                
                return request
        
        except Exception as e:
            logger.error(f"Failed to get approval request: {e}")
            return None
    
    def respond(
        self,
        request_id: str,
        approved: bool,
        user_comment: Optional[str] = None
    ) -> bool:
        """
        响应审批请求
        
        Args:
            request_id: 请求ID
            approved: 是否批准
            user_comment: 用户评论
        
        Returns:
            是否成功
        """
        try:
            status = ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED
            
            with self._get_conn() as conn:
                cursor = conn.execute("""
                    UPDATE approval_requests
                    SET status = ?, user_comment = ?, responded_at = CURRENT_TIMESTAMP
                    WHERE request_id = ? AND status = ?
                """, (status.value, user_comment, request_id, ApprovalStatus.PENDING.value))
                
                conn.commit()
                
                if cursor.rowcount == 0:
                    logger.warning(f"Approval request not found or already responded: {request_id}")
                    return False
            
            logger.info(f"Approval request responded: {request_id} -> {status.value}")
            
            # 通知等待的 Future
            if request_id in self._pending_requests:
                future = self._pending_requests.pop(request_id)
                if not future.done():
                    future.set_result(approved)
            
            return True
        
        except Exception as e:
            logger.error(f"Failed to respond to approval request: {e}")
            return False
    
    async def wait_for_approval(
        self,
        request_id: str,
        timeout_seconds: Optional[int] = None
    ) -> bool:
        """
        异步等待审批结果
        
        Args:
            request_id: 请求ID
            timeout_seconds: 超时时间（秒）
        
        Returns:
            是否批准
        
        Raises:
            TimeoutError: 超时
        """
        # 检查是否已有结果
        request = self.get_request(request_id)
        if not request:
            raise ValueError(f"Approval request not found: {request_id}")
        
        if request['status'] == ApprovalStatus.APPROVED.value:
            return True
        elif request['status'] == ApprovalStatus.DENIED.value:
            return False
        elif request['status'] != ApprovalStatus.PENDING.value:
            raise ValueError(f"Invalid approval status: {request['status']}")
        
        # 创建 Future 等待结果
        if request_id not in self._pending_requests:
            self._pending_requests[request_id] = asyncio.Future()
        
        future = self._pending_requests[request_id]
        timeout = timeout_seconds or self.default_timeout
        
        try:
            approved = await asyncio.wait_for(future, timeout=timeout)
            return approved
        
        except asyncio.TimeoutError:
            # 超时，标记为 TIMEOUT
            with self._get_conn() as conn:
                conn.execute("""
                    UPDATE approval_requests
                    SET status = ?
                    WHERE request_id = ? AND status = ?
                """, (ApprovalStatus.TIMEOUT.value, request_id, ApprovalStatus.PENDING.value))
                conn.commit()
            
            logger.warning(f"Approval request timeout: {request_id}")
            raise TimeoutError(f"Approval request timeout: {request_id}")
    
    def cleanup_expired(self) -> int:
        """清理过期请求，返回清理数量"""
        try:
            with self._get_conn() as conn:
                cursor = conn.execute("""
                    UPDATE approval_requests
                    SET status = ?
                    WHERE status = ? AND expires_at < CURRENT_TIMESTAMP
                """, (ApprovalStatus.EXPIRED.value, ApprovalStatus.PENDING.value))
                
                conn.commit()
                count = cursor.rowcount
            
            if count > 0:
                logger.info(f"Cleaned up {count} expired approval requests")
            
            return count
        
        except Exception as e:
            logger.error(f"Failed to cleanup expired requests: {e}")
            return 0


# 全局单例
_approval_service: Optional[ApprovalService] = None


def get_approval_service() -> ApprovalService:
    """获取全局 ApprovalService 实例"""
    global _approval_service
    if _approval_service is None:
        _approval_service = ApprovalService()
    return _approval_service
