# server/app/services/approval_service.py
"""
ApprovalService — 审批生命周期管理

使用 avatar.db（统一数据库），不再维护独立 approval.db。
表：approval_requests、grants
"""
from __future__ import annotations

import fnmatch
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional, List, Dict, Any
from sqlmodel import Session, select

from app.db.database import engine
from app.db.system import ApprovalRequest, Grant

logger = logging.getLogger(__name__)


class ApprovalStatus(str, Enum):
    PENDING  = "pending"
    APPROVED = "approved"
    DENIED   = "denied"
    EXPIRED  = "expired"
    TIMEOUT  = "timeout"


class ApprovalDecision(str, Enum):
    ALLOW   = "allow"
    DENY    = "deny"
    PENDING = "pending"


class PathAccessResult:
    """Guard 层返回的结构化结果"""
    __slots__ = ("decision", "request_id", "reason")

    def __init__(
        self,
        decision: ApprovalDecision,
        request_id: Optional[str] = None,
        reason: Optional[str] = None,
    ):
        self.decision   = decision
        self.request_id = request_id
        self.reason     = reason


class ApprovalService:
    """
    审批服务（幂等协议）+ Grant Store

    职责：
    - 创建 / 查询 / 响应审批请求
    - 维护 grant store（已批准的路径授权）
    - 提供 check_path_access() 供 FsAccessGuard 调用
    """

    def __init__(self, default_timeout: int = 60):
        self.default_timeout = default_timeout
        self._pending_futures: Dict[str, asyncio.Future] = {}

    # ------------------------------------------------------------------
    # Grant Store
    # ------------------------------------------------------------------

    def check_path_access(
        self,
        path: str,
        operation: str,
        scope: str = "session",
        scope_id: Optional[str] = None,
    ) -> PathAccessResult:
        """
        检查路径访问权限。
        先查 grant store，有匹配的有效 grant 直接 ALLOW，否则返回 PENDING。
        """
        with Session(engine) as session:
            stmt = select(Grant).where(
                Grant.revoked == False,
                Grant.scope == scope,
            )
            if scope_id:
                stmt = stmt.where(Grant.scope_id == scope_id)

            grants = session.exec(stmt).all()

        now = datetime.now(timezone.utc)
        for grant in grants:
            # 检查时效
            if grant.expires_at and grant.expires_at < now:
                continue
            # 检查操作
            # operation="*" 表示"任意操作均可"，此时只要 grant 存在即视为匹配
            if operation != "*" and operation not in grant.operations and "*" not in grant.operations:
                continue
            # 检查路径（支持 glob 匹配）
            if fnmatch.fnmatch(path, grant.path_pattern) or path.startswith(grant.path_pattern.rstrip("*")):
                return PathAccessResult(decision=ApprovalDecision.ALLOW, reason="grant_matched")

        return PathAccessResult(decision=ApprovalDecision.PENDING, reason="no_grant")

    def create_grant(
        self,
        path_pattern: str,
        operations: List[str],
        scope: str = "session",
        scope_id: Optional[str] = None,
        approval_request_id: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> Grant:
        """创建授权记录"""
        expires_at = None
        if ttl_seconds:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

        grant = Grant(
            approval_request_id=approval_request_id,
            path_pattern=path_pattern,
            operations=operations,
            scope=scope,
            scope_id=scope_id,
            expires_at=expires_at,
        )
        with Session(engine) as session:
            session.add(grant)
            session.commit()
            session.refresh(grant)

        logger.info(f"[ApprovalService] Grant created: {path_pattern} ops={operations} scope={scope}/{scope_id}")
        return grant

    def revoke_grant(self, grant_id: str) -> bool:
        with Session(engine) as session:
            grant = session.get(Grant, grant_id)
            if not grant:
                return False
            grant.revoked = True
            session.add(grant)
            session.commit()
        return True

    # ------------------------------------------------------------------
    # Approval Requests
    # ------------------------------------------------------------------

    def create_request(
        self,
        request_id: str,
        message: str,
        operation: str,
        task_id: Optional[str] = None,
        step_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        timeout_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """创建审批请求（幂等）"""
        existing = self.get_request(request_id)
        if existing:
            return existing

        timeout = timeout_seconds or self.default_timeout
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=timeout)

        req = ApprovalRequest(
            request_id=request_id,
            task_id=task_id,
            step_id=step_id,
            message=message,
            operation=operation,
            details=details,
            expires_at=expires_at,
            status=ApprovalStatus.PENDING.value,
        )
        with Session(engine) as session:
            session.add(req)
            session.commit()

        logger.info(f"[ApprovalService] Request created: {request_id}")

        # 通过 socket 推送审批请求给前端
        payload = {
            "request_id": request_id,
            "message": message,
            "operation": operation,
            "status": ApprovalStatus.PENDING.value,
            "expires_at": expires_at.isoformat(),
            "task_id": task_id,
            "step_id": step_id,
            "details": details,
        }
        try:
            from app.io.manager import SocketManager
            socket_mgr = SocketManager.get_instance()
            loop = asyncio.get_running_loop()
            loop.create_task(socket_mgr.emit("server_event", {
                "type": "approval_request",
                "payload": payload,
            }))
        except RuntimeError:
            # 不在 async 上下文（理论上不应发生，create_request 总在 async 路径调用）
            logger.warning("[ApprovalService] No running event loop, approval_request socket push skipped")
        except Exception as e:
            logger.warning(f"[ApprovalService] Failed to push approval_request via socket: {e}")

        return payload

    def get_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        with Session(engine) as session:
            req = session.get(ApprovalRequest, request_id)
            if not req:
                return None
            return {
                "request_id": req.request_id,
                "message": req.message,
                "operation": req.operation,
                "status": req.status,
                "details": req.details,
                "expires_at": req.expires_at.isoformat() if req.expires_at else None,
                "task_id": req.task_id,
                "step_id": req.step_id,
            }

    def respond(
        self,
        request_id: str,
        approved: bool,
        user_comment: Optional[str] = None,
        # grant 参数（批准时自动创建 grant）
        path_pattern: Optional[str] = None,
        operations: Optional[List[str]] = None,
        scope: str = "session",
        scope_id: Optional[str] = None,
        grant_ttl_seconds: Optional[int] = None,
    ) -> bool:
        """
        响应审批请求。
        批准时自动创建 grant（如果提供了 path_pattern）。
        """
        status = ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED

        with Session(engine) as session:
            req = session.get(ApprovalRequest, request_id)
            if not req or req.status != ApprovalStatus.PENDING.value:
                logger.warning(f"[ApprovalService] Request not found or already responded: {request_id}")
                return False
            req.status = status.value
            req.user_comment = user_comment
            req.responded_at = datetime.now(timezone.utc)
            session.add(req)
            session.commit()

        logger.info(f"[ApprovalService] Request responded: {request_id} → {status.value}")

        # 批准时自动创建 grant
        if approved and path_pattern:
            self.create_grant(
                path_pattern=path_pattern,
                operations=operations or ["read", "write"],
                scope=scope,
                scope_id=scope_id,
                approval_request_id=request_id,
                ttl_seconds=grant_ttl_seconds,
            )

        # 通知等待的 Future
        if request_id in self._pending_futures:
            future = self._pending_futures.pop(request_id)
            if not future.done():
                future.set_result(approved)

        return True

    async def wait_for_approval(
        self,
        request_id: str,
        timeout_seconds: Optional[int] = None,
    ) -> bool:
        """异步等待审批结果"""
        req = self.get_request(request_id)
        if not req:
            raise ValueError(f"Approval request not found: {request_id}")

        if req["status"] == ApprovalStatus.APPROVED.value:
            return True
        if req["status"] == ApprovalStatus.DENIED.value:
            return False
        if req["status"] != ApprovalStatus.PENDING.value:
            raise ValueError(f"Invalid approval status: {req['status']}")

        if request_id not in self._pending_futures:
            loop = asyncio.get_running_loop()
            self._pending_futures[request_id] = loop.create_future()

        future = self._pending_futures[request_id]
        timeout = timeout_seconds or self.default_timeout

        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
        except asyncio.TimeoutError:
            with Session(engine) as session:
                r = session.get(ApprovalRequest, request_id)
                if r and r.status == ApprovalStatus.PENDING.value:
                    r.status = ApprovalStatus.TIMEOUT.value
                    session.add(r)
                    session.commit()
            logger.warning(f"[ApprovalService] Request timeout: {request_id}")
            raise TimeoutError(f"Approval request timeout: {request_id}")

    def cleanup_expired(self) -> int:
        """将过期的 PENDING 请求标记为 EXPIRED"""
        now = datetime.now(timezone.utc)
        with Session(engine) as session:
            stmt = select(ApprovalRequest).where(
                ApprovalRequest.status == ApprovalStatus.PENDING.value,
                ApprovalRequest.expires_at < now,
            )
            reqs = session.exec(stmt).all()
            for r in reqs:
                r.status = ApprovalStatus.EXPIRED.value
            session.commit()
            count = len(reqs)

        if count:
            logger.info(f"[ApprovalService] Cleaned up {count} expired requests")
        return count


# 全局单例
_approval_service: Optional[ApprovalService] = None


def get_approval_service() -> ApprovalService:
    global _approval_service
    if _approval_service is None:
        _approval_service = ApprovalService()
    return _approval_service
