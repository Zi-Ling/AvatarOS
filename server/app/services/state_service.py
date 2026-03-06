# server/app/services/state_service.py

from __future__ import annotations

import json
import sqlite3
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# 状态数据库路径
STATE_DB_PATH = Path.home() / ".avatarOS" / "state.db"


class StateService:
    """
    短期状态管理服务
    
    支持三种作用域：
    - task: 任务级别（单次任务执行）
    - session: 会话级别（用户对话会话）
    - user: 用户级别（跨会话持久化）
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or STATE_DB_PATH
        self._init_db()
    
    def _init_db(self):
        """初始化数据库表"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS state (
                    scope TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    expires_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (scope, scope_id, key)
                )
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_expires_at ON state(expires_at)
            """)
            
            conn.commit()
            logger.info(f"State database initialized at {self.db_path}")
    
    @contextmanager
    def _get_conn(self):
        """获取数据库连接"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def set(
        self,
        scope: str,
        scope_id: str,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = None
    ) -> bool:
        """
        设置状态值
        
        Args:
            scope: 作用域类型 (task/session/user)
            scope_id: 作用域ID
            key: 键名
            value: 值（会被序列化为JSON）
            ttl_seconds: 过期时间（秒），None表示永不过期
        
        Returns:
            是否成功
        """
        try:
            value_json = json.dumps(value, ensure_ascii=False)
            expires_at = None
            
            if ttl_seconds:
                expires_at = (datetime.now() + timedelta(seconds=ttl_seconds)).isoformat()
            
            with self._get_conn() as conn:
                conn.execute("""
                    INSERT INTO state (scope, scope_id, key, value, expires_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(scope, scope_id, key) DO UPDATE SET
                        value = excluded.value,
                        expires_at = excluded.expires_at,
                        updated_at = CURRENT_TIMESTAMP
                """, (scope, scope_id, key, value_json, expires_at))
                
                conn.commit()
            
            logger.debug(f"State set: {scope}/{scope_id}/{key}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to set state: {e}")
            return False
    
    def get(
        self,
        scope: str,
        scope_id: str,
        key: str,
        default: Any = None
    ) -> Any:
        """
        获取状态值
        
        Args:
            scope: 作用域类型
            scope_id: 作用域ID
            key: 键名
            default: 默认值
        
        Returns:
            状态值，如果不存在或已过期返回default
        """
        try:
            with self._get_conn() as conn:
                row = conn.execute("""
                    SELECT value, expires_at FROM state
                    WHERE scope = ? AND scope_id = ? AND key = ?
                """, (scope, scope_id, key)).fetchone()
                
                if not row:
                    return default
                
                # 检查是否过期
                if row['expires_at']:
                    expires_at = datetime.fromisoformat(row['expires_at'])
                    if datetime.now() > expires_at:
                        # 已过期，删除并返回默认值
                        self.delete(scope, scope_id, key)
                        return default
                
                return json.loads(row['value'])
        
        except Exception as e:
            logger.error(f"Failed to get state: {e}")
            return default
    
    def delete(self, scope: str, scope_id: str, key: str) -> bool:
        """删除状态值"""
        try:
            with self._get_conn() as conn:
                conn.execute("""
                    DELETE FROM state
                    WHERE scope = ? AND scope_id = ? AND key = ?
                """, (scope, scope_id, key))
                
                conn.commit()
            
            logger.debug(f"State deleted: {scope}/{scope_id}/{key}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to delete state: {e}")
            return False
    
    def clear_scope(self, scope: str, scope_id: str) -> bool:
        """清空指定作用域的所有状态"""
        try:
            with self._get_conn() as conn:
                conn.execute("""
                    DELETE FROM state
                    WHERE scope = ? AND scope_id = ?
                """, (scope, scope_id))
                
                conn.commit()
            
            logger.info(f"Scope cleared: {scope}/{scope_id}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to clear scope: {e}")
            return False
    
    def cleanup_expired(self) -> int:
        """清理过期状态，返回清理数量"""
        try:
            with self._get_conn() as conn:
                cursor = conn.execute("""
                    DELETE FROM state
                    WHERE expires_at IS NOT NULL
                    AND expires_at < CURRENT_TIMESTAMP
                """)
                
                conn.commit()
                count = cursor.rowcount
            
            if count > 0:
                logger.info(f"Cleaned up {count} expired states")
            
            return count
        
        except Exception as e:
            logger.error(f"Failed to cleanup expired states: {e}")
            return 0


# 全局单例
_state_service: Optional[StateService] = None


def get_state_service() -> StateService:
    """获取全局 StateService 实例"""
    global _state_service
    if _state_service is None:
        _state_service = StateService()
    return _state_service
