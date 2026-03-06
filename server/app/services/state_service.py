# server/app/services/state_service.py
"""
StateService — 短期 KV 状态管理

使用 avatar.db（统一数据库），不再维护独立 state.db。
表：kv_state
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Any
from sqlmodel import Session, select

from app.db.database import engine
from app.db.system import KVState

logger = logging.getLogger(__name__)


class StateService:
    """
    短期状态管理服务，支持三种作用域：
    - task:    任务级别（单次任务执行）
    - session: 会话级别（用户对话会话）
    - user:    用户级别（跨会话持久化）
    """

    def set(
        self,
        scope: str,
        scope_id: str,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        try:
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=ttl_seconds) if ttl_seconds else None

            with Session(engine) as session:
                stmt = select(KVState).where(
                    KVState.scope == scope,
                    KVState.scope_id == scope_id,
                    KVState.key == key,
                )
                existing = session.exec(stmt).first()

                if existing:
                    existing.value = {"v": value}
                    existing.expires_at = expires_at
                    existing.updated_at = now
                    session.add(existing)
                else:
                    session.add(KVState(
                        scope=scope,
                        scope_id=scope_id,
                        key=key,
                        value={"v": value},
                        ttl_seconds=ttl_seconds,
                        expires_at=expires_at,
                    ))
                session.commit()

            logger.debug(f"[StateService] set {scope}/{scope_id}/{key}")
            return True
        except Exception as e:
            logger.error(f"[StateService] set failed: {e}")
            return False

    def get(
        self,
        scope: str,
        scope_id: str,
        key: str,
        default: Any = None,
    ) -> Any:
        try:
            with Session(engine) as session:
                stmt = select(KVState).where(
                    KVState.scope == scope,
                    KVState.scope_id == scope_id,
                    KVState.key == key,
                )
                row = session.exec(stmt).first()

            if not row:
                return default

            if row.expires_at and row.expires_at < datetime.now(timezone.utc):
                self.delete(scope, scope_id, key)
                return default

            return row.value.get("v") if row.value else default
        except Exception as e:
            logger.error(f"[StateService] get failed: {e}")
            return default

    def delete(self, scope: str, scope_id: str, key: str) -> bool:
        try:
            with Session(engine) as session:
                stmt = select(KVState).where(
                    KVState.scope == scope,
                    KVState.scope_id == scope_id,
                    KVState.key == key,
                )
                row = session.exec(stmt).first()
                if row:
                    session.delete(row)
                    session.commit()
            return True
        except Exception as e:
            logger.error(f"[StateService] delete failed: {e}")
            return False

    def clear_scope(self, scope: str, scope_id: str) -> bool:
        try:
            with Session(engine) as session:
                stmt = select(KVState).where(
                    KVState.scope == scope,
                    KVState.scope_id == scope_id,
                )
                rows = session.exec(stmt).all()
                for r in rows:
                    session.delete(r)
                session.commit()
            logger.info(f"[StateService] Scope cleared: {scope}/{scope_id}")
            return True
        except Exception as e:
            logger.error(f"[StateService] clear_scope failed: {e}")
            return False

    def cleanup_expired(self) -> int:
        try:
            now = datetime.now(timezone.utc)
            with Session(engine) as session:
                stmt = select(KVState).where(
                    KVState.expires_at != None,
                    KVState.expires_at < now,
                )
                rows = session.exec(stmt).all()
                for r in rows:
                    session.delete(r)
                session.commit()
                count = len(rows)
            if count:
                logger.info(f"[StateService] Cleaned up {count} expired states")
            return count
        except Exception as e:
            logger.error(f"[StateService] cleanup_expired failed: {e}")
            return 0


# 全局单例
_state_service: Optional[StateService] = None


def get_state_service() -> StateService:
    global _state_service
    if _state_service is None:
        _state_service = StateService()
    return _state_service
