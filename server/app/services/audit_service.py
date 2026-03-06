# server/app/services/audit_service.py

from __future__ import annotations

import json
import sqlite3
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# 审计日志数据库路径
AUDIT_DB_PATH = Path.home() / ".avatarOS" / "audit.db"


class AuditService:
    """
    审计日志服务
    
    记录所有技能执行的审计日志，用于：
    - 安全审计
    - 问题排查
    - 行为分析
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or AUDIT_DB_PATH
        self._init_db()
    
    def _init_db(self):
        """初始化数据库表"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user_id TEXT,
                    task_id TEXT,
                    skill_name TEXT,
                    operation TEXT,
                    details TEXT,
                    approved BOOLEAN,
                    result TEXT
                )
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_task_id ON audit_log(task_id)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp ON audit_log(timestamp)
            """)
            
            conn.commit()
            logger.info(f"Audit database initialized at {self.db_path}")
    
    @contextmanager
    def _get_conn(self):
        """获取数据库连接"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def log(
        self,
        skill_name: str,
        operation: str,
        result: str,
        task_id: Optional[str] = None,
        user_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        approved: Optional[bool] = None
    ) -> bool:
        """
        记录审计日志
        
        Args:
            skill_name: 技能名称
            operation: 操作类型
            result: 执行结果 (success/failed)
            task_id: 任务ID
            user_id: 用户ID
            details: 详细信息（JSON）
            approved: 是否经过审批
        
        Returns:
            是否成功
        """
        try:
            details_json = json.dumps(details, ensure_ascii=False) if details else None
            
            with self._get_conn() as conn:
                conn.execute("""
                    INSERT INTO audit_log (
                        user_id, task_id, skill_name, operation,
                        details, approved, result
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id, task_id, skill_name, operation,
                    details_json, approved, result
                ))
                
                conn.commit()
            
            logger.debug(f"Audit logged: {skill_name}/{operation} -> {result}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to log audit: {e}")
            return False
    
    def query(
        self,
        task_id: Optional[str] = None,
        user_id: Optional[str] = None,
        skill_name: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        查询审计日志
        
        Args:
            task_id: 任务ID过滤
            user_id: 用户ID过滤
            skill_name: 技能名称过滤
            limit: 返回数量限制
        
        Returns:
            审计日志列表
        """
        try:
            query = "SELECT * FROM audit_log WHERE 1=1"
            params = []
            
            if task_id:
                query += " AND task_id = ?"
                params.append(task_id)
            
            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)
            
            if skill_name:
                query += " AND skill_name = ?"
                params.append(skill_name)
            
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            with self._get_conn() as conn:
                rows = conn.execute(query, params).fetchall()
            
            logs = []
            for row in rows:
                log_entry = dict(row)
                if log_entry.get('details'):
                    log_entry['details'] = json.loads(log_entry['details'])
                logs.append(log_entry)
            
            return logs
        
        except Exception as e:
            logger.error(f"Failed to query audit logs: {e}")
            return []
    
    def cleanup_old_logs(self, days: int = 90) -> int:
        """
        清理旧日志
        
        Args:
            days: 保留天数
        
        Returns:
            清理数量
        """
        try:
            with self._get_conn() as conn:
                cursor = conn.execute("""
                    DELETE FROM audit_log
                    WHERE timestamp < datetime('now', '-' || ? || ' days')
                """, (days,))
                
                conn.commit()
                count = cursor.rowcount
            
            if count > 0:
                logger.info(f"Cleaned up {count} old audit logs (older than {days} days)")
            
            return count
        
        except Exception as e:
            logger.error(f"Failed to cleanup old logs: {e}")
            return 0


# 全局单例
_audit_service: Optional[AuditService] = None


def get_audit_service() -> AuditService:
    """获取全局 AuditService 实例"""
    global _audit_service
    if _audit_service is None:
        _audit_service = AuditService()
    return _audit_service
