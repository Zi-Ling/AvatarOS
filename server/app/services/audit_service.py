# server/app/services/audit_service.py
"""
AuditService — 审计日志

使用 avatar.db（统一数据库），不再维护独立 audit.db。
表：audit_logs
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from sqlmodel import Session, select

from app.db.database import engine
from app.db.system import AuditLog

logger = logging.getLogger(__name__)


class AuditService:

    def log(
        self,
        event_type: str,
        actor: Optional[str] = None,
        resource: Optional[str] = None,
        operation: Optional[str] = None,
        outcome: str = "success",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            with Session(engine) as session:
                session.add(AuditLog(
                    event_type=event_type,
                    actor=actor,
                    resource=resource,
                    operation=operation,
                    outcome=outcome,
                    details=details,
                ))
                session.commit()
            logger.debug(f"[AuditService] {event_type} {outcome} actor={actor} resource={resource}")
        except Exception as e:
            logger.error(f"[AuditService] log failed: {e}")

    def query(
        self,
        event_type: Optional[str] = None,
        actor: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        try:
            with Session(engine) as session:
                stmt = select(AuditLog)
                if event_type:
                    stmt = stmt.where(AuditLog.event_type == event_type)
                if actor:
                    stmt = stmt.where(AuditLog.actor == actor)
                stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit)
                rows = session.exec(stmt).all()
                return [
                    {
                        "id": r.id,
                        "event_type": r.event_type,
                        "actor": r.actor,
                        "resource": r.resource,
                        "operation": r.operation,
                        "outcome": r.outcome,
                        "details": r.details,
                        "created_at": r.created_at.isoformat(),
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.error(f"[AuditService] query failed: {e}")
            return []


# 全局单例
_audit_service: Optional[AuditService] = None


def get_audit_service() -> AuditService:
    global _audit_service
    if _audit_service is None:
        _audit_service = AuditService()
    return _audit_service
