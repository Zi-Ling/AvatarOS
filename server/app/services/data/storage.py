"""
StorageBackend — 3 个 Protocol + SQLiteBackend 实现

RecordStorage: 核心业务对象 CRUD
WorkflowStorage: 提案、审计日志、对象关联
SchemaStorage: Backend 初始化与 migration 支撑

SQLiteBackend 同时实现全部 3 个 Protocol。
所有写操作使用事务，异常时回滚；所有 SQL 使用参数化查询防注入。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import aiosqlite

from .models import (
    DataErrorCode,
    FilterCondition,
    FilterOperator,
    RecordNotFoundError,
    StorageError,
    VersionConflictError,
)

logger = logging.getLogger(__name__)


# ── Protocols ──


@runtime_checkable
class RecordStorage(Protocol):
    """核心业务对象 CRUD"""

    async def insert(self, object_type: str, record: dict[str, Any]) -> dict[str, Any]: ...

    async def get_by_id(self, object_type: str, record_id: str) -> dict[str, Any] | None: ...

    async def update(
        self, object_type: str, record_id: str, changes: dict[str, Any], expected_version: int
    ) -> dict[str, Any]: ...

    async def archive(self, object_type: str, record_id: str, expected_version: int) -> dict[str, Any]: ...

    async def list_records(
        self,
        object_type: str,
        filters: list[FilterCondition],
        sort_by: str | None,
        sort_order: str,
        offset: int,
        limit: int,
        include_archived: bool,
    ) -> tuple[list[dict[str, Any]], int]: ...

    async def search_text(
        self,
        object_type: str,
        keyword: str,
        text_fields: list[str],
        offset: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]: ...


@runtime_checkable
class WorkflowStorage(Protocol):
    """提案、审计日志、对象关联"""

    async def insert_proposal(self, proposal: dict[str, Any]) -> None: ...

    async def get_proposal(self, proposal_id: str) -> dict[str, Any] | None: ...

    async def update_proposal_status(self, proposal_id: str, status: str, **kwargs: Any) -> None: ...

    async def insert_audit_log(self, log_entry: dict[str, Any]) -> None: ...

    async def insert_relation(self, relation: dict[str, Any]) -> dict[str, Any]: ...

    async def get_relations(self, object_type: str, record_id: str) -> list[dict[str, Any]]: ...

    async def list_schema_audit_logs(self, limit: int = 20) -> list[dict[str, Any]]:
        """查询 schema 变更审计日志（record_id='__schema__' 的条目）。

        这是 schema 变更历史的专用窄接口，仅用于 describe_objects 的 recent_schema_changes。
        未来可能被通用审计查询接口替代。
        """
        ...


@runtime_checkable
class SchemaStorage(Protocol):
    """Backend 初始化与 migration 支撑"""

    async def initialize(self) -> None: ...

    async def execute_ddl(self, statements: list[str]) -> None: ...

    async def get_table_columns(self, table_name: str) -> list[str]: ...

    async def get_schema_version(self, object_type: str) -> int | None: ...

    async def set_schema_version(self, object_type: str, version: int) -> None: ...


# ── Filter → SQL 转换 ──

_OP_MAP: dict[FilterOperator, str] = {
    FilterOperator.EQ: "= ?",
    FilterOperator.NEQ: "!= ?",
    FilterOperator.GT: "> ?",
    FilterOperator.GTE: ">= ?",
    FilterOperator.LT: "< ?",
    FilterOperator.LTE: "<= ?",
    FilterOperator.LIKE: "LIKE ?",
    FilterOperator.IS_NULL: "IS NULL",
    FilterOperator.IS_NOT_NULL: "IS NOT NULL",
}


def _build_where(
    filters: list[FilterCondition], include_archived: bool
) -> tuple[str, list[Any]]:
    """将 FilterCondition 列表转换为 WHERE 子句 + 参数列表（AND 组合）"""
    clauses: list[str] = []
    params: list[Any] = []

    if not include_archived:
        clauses.append("archived_at IS NULL")

    for f in filters:
        if f.operator == FilterOperator.IN:
            if not isinstance(f.value, (list, tuple)) or len(f.value) == 0:
                continue
            placeholders = ", ".join("?" for _ in f.value)
            clauses.append(f'"{f.field}" IN ({placeholders})')
            params.extend(f.value)
        elif f.operator in (FilterOperator.IS_NULL, FilterOperator.IS_NOT_NULL):
            clauses.append(f'"{f.field}" {_OP_MAP[f.operator]}')
        else:
            clauses.append(f'"{f.field}" {_OP_MAP[f.operator]}')
            params.append(f.value)

    where = " AND ".join(clauses) if clauses else "1=1"
    return where, params


def _table_name(object_type: str) -> str:
    """对象类型 → 表名（小写）"""
    return object_type.lower()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: aiosqlite.Row, description: list) -> dict[str, Any]:
    """将 sqlite Row 转换为 dict"""
    return {desc[0]: row[i] for i, desc in enumerate(description)}


# ── 系统表 DDL ──

_SYSTEM_TABLES_DDL = [
    """CREATE TABLE IF NOT EXISTS schema_version (
        object_type TEXT PRIMARY KEY,
        version INTEGER NOT NULL,
        updated_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS change_proposal (
        proposal_id TEXT PRIMARY KEY,
        object_type TEXT NOT NULL,
        operation TEXT NOT NULL,
        record_id TEXT,
        changes TEXT NOT NULL,
        summary TEXT,
        diff_snapshot TEXT,
        risk_level TEXT DEFAULT 'low',
        status TEXT DEFAULT 'pending',
        proposed_by TEXT DEFAULT 'system',
        approval_mode TEXT DEFAULT 'manual',
        approved_by TEXT,
        approved_at TEXT,
        rejected_reason TEXT,
        expected_version INTEGER,
        expires_at TEXT,
        trace_id TEXT,
        workspace_id TEXT NOT NULL,
        created_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS audit_log (
        change_id TEXT PRIMARY KEY,
        object_type TEXT NOT NULL,
        record_id TEXT NOT NULL,
        operation TEXT NOT NULL,
        before_snapshot TEXT,
        after_snapshot TEXT NOT NULL,
        proposal_id TEXT,
        actor TEXT,
        trace_id TEXT,
        reason TEXT,
        changed_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS object_relation (
        relation_id TEXT PRIMARY KEY,
        relation_type TEXT NOT NULL,
        source_type TEXT NOT NULL,
        source_id TEXT NOT NULL,
        target_type TEXT NOT NULL,
        target_id TEXT NOT NULL,
        metadata TEXT,
        created_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS dynamic_object_definitions (
        object_name TEXT PRIMARY KEY,
        definition_json TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        created_by TEXT DEFAULT 'agent',
        created_at TEXT,
        updated_at TEXT,
        schema_version INTEGER DEFAULT 1,
        status TEXT DEFAULT 'active'
    )""",
]


class SQLiteBackend:
    """
    SQLite 存储后端，同时实现 RecordStorage + WorkflowStorage + SchemaStorage。
    使用 aiosqlite 异步驱动。
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None

    async def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise StorageError("Backend 未初始化，请先调用 initialize()")
        return self._db

    # ── SchemaStorage ──

    async def initialize(self) -> None:
        """建立连接，确保系统表存在"""
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        for ddl in _SYSTEM_TABLES_DDL:
            await self._db.execute(ddl)
        await self._db.commit()
        logger.info(f"SQLiteBackend 初始化完成: {self._db_path}")

    async def execute_ddl(self, statements: list[str]) -> None:
        db = await self._conn()
        for stmt in statements:
            await db.execute(stmt)
        await db.commit()

    async def get_table_columns(self, table_name: str) -> list[str]:
        db = await self._conn()
        cursor = await db.execute(f'PRAGMA table_info("{table_name}")')
        rows = await cursor.fetchall()
        return [row[1] for row in rows]  # column name is index 1

    async def get_schema_version(self, object_type: str) -> int | None:
        db = await self._conn()
        cursor = await db.execute(
            "SELECT version FROM schema_version WHERE object_type = ?", (object_type,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def set_schema_version(self, object_type: str, version: int) -> None:
        db = await self._conn()
        await db.execute(
            "INSERT OR REPLACE INTO schema_version (object_type, version, updated_at) VALUES (?, ?, ?)",
            (object_type, version, _now_iso()),
        )
        await db.commit()


    # ── RecordStorage ──

    async def insert(self, object_type: str, record: dict[str, Any]) -> dict[str, Any]:
        db = await self._conn()
        table = _table_name(object_type)
        columns = list(record.keys())
        placeholders = ", ".join("?" for _ in columns)
        col_names = ", ".join(f'"{c}"' for c in columns)
        sql = f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders})'
        try:
            await db.execute(sql, list(record.values()))
            await db.commit()
        except Exception as e:
            await db.rollback()
            raise StorageError(f"插入失败: {e}") from e
        return record

    async def get_by_id(self, object_type: str, record_id: str) -> dict[str, Any] | None:
        db = await self._conn()
        table = _table_name(object_type)
        cursor = await db.execute(f'SELECT * FROM "{table}" WHERE id = ?', (record_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def update(
        self, object_type: str, record_id: str, changes: dict[str, Any], expected_version: int
    ) -> dict[str, Any]:
        db = await self._conn()
        table = _table_name(object_type)
        # 乐观锁：WHERE id = ? AND version = ?
        set_clauses = ", ".join(f'"{k}" = ?' for k in changes.keys())
        sql = f'UPDATE "{table}" SET {set_clauses} WHERE id = ? AND version = ?'
        params = list(changes.values()) + [record_id, expected_version]
        try:
            cursor = await db.execute(sql, params)
            if cursor.rowcount == 0:
                await db.rollback()
                # 检查记录是否存在
                check = await db.execute(f'SELECT version FROM "{table}" WHERE id = ?', (record_id,))
                row = await check.fetchone()
                if row is None:
                    raise RecordNotFoundError(f"记录不存在: {record_id}")
                raise VersionConflictError(
                    f"版本冲突: 期望 {expected_version}, 实际 {row[0]}"
                )
            await db.commit()
        except (RecordNotFoundError, VersionConflictError):
            raise
        except Exception as e:
            await db.rollback()
            raise StorageError(f"更新失败: {e}") from e
        # 返回更新后的完整记录
        return await self.get_by_id(object_type, record_id)  # type: ignore[return-value]

    async def archive(self, object_type: str, record_id: str, expected_version: int) -> dict[str, Any]:
        now = _now_iso()
        changes = {
            "archived_at": now,
            "updated_at": now,
            "version": expected_version + 1,
        }
        return await self.update(object_type, record_id, changes, expected_version)

    async def list_records(
        self,
        object_type: str,
        filters: list[FilterCondition],
        sort_by: str | None,
        sort_order: str,
        offset: int,
        limit: int,
        include_archived: bool,
    ) -> tuple[list[dict[str, Any]], int]:
        db = await self._conn()
        table = _table_name(object_type)
        where, params = _build_where(filters, include_archived)

        # 总数
        count_sql = f'SELECT COUNT(*) FROM "{table}" WHERE {where}'
        cursor = await db.execute(count_sql, params)
        total = (await cursor.fetchone())[0]

        # 数据
        order = ""
        if sort_by:
            direction = "DESC" if sort_order.lower() == "desc" else "ASC"
            order = f' ORDER BY "{sort_by}" {direction}'
        data_sql = f'SELECT * FROM "{table}" WHERE {where}{order} LIMIT ? OFFSET ?'
        cursor = await db.execute(data_sql, params + [limit, offset])
        rows = await cursor.fetchall()
        records = [dict(row) for row in rows]
        return records, total

    async def search_text(
        self,
        object_type: str,
        keyword: str,
        text_fields: list[str],
        offset: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        if not text_fields:
            return [], 0
        db = await self._conn()
        table = _table_name(object_type)
        like_pattern = f"%{keyword}%"
        or_clauses = " OR ".join(f'"{f}" LIKE ?' for f in text_fields)
        where = f"({or_clauses}) AND archived_at IS NULL"
        params = [like_pattern] * len(text_fields)

        count_sql = f'SELECT COUNT(*) FROM "{table}" WHERE {where}'
        cursor = await db.execute(count_sql, params)
        total = (await cursor.fetchone())[0]

        data_sql = f'SELECT * FROM "{table}" WHERE {where} LIMIT ? OFFSET ?'
        cursor = await db.execute(data_sql, params + [limit, offset])
        rows = await cursor.fetchall()
        records = [dict(row) for row in rows]
        return records, total


    # ── WorkflowStorage ──

    async def insert_proposal(self, proposal: dict[str, Any]) -> None:
        db = await self._conn()
        # JSON 序列化 dict 字段
        row = dict(proposal)
        for key in ("changes", "diff_snapshot"):
            if key in row and row[key] is not None:
                row[key] = json.dumps(row[key], ensure_ascii=False, default=str)
        columns = list(row.keys())
        placeholders = ", ".join("?" for _ in columns)
        col_names = ", ".join(f'"{c}"' for c in columns)
        sql = f"INSERT INTO change_proposal ({col_names}) VALUES ({placeholders})"
        try:
            await db.execute(sql, list(row.values()))
            await db.commit()
        except Exception as e:
            await db.rollback()
            raise StorageError(f"插入提案失败: {e}") from e

    async def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        db = await self._conn()
        cursor = await db.execute(
            "SELECT * FROM change_proposal WHERE proposal_id = ?", (proposal_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        result = dict(row)
        # JSON 反序列化
        for key in ("changes", "diff_snapshot"):
            if result.get(key) and isinstance(result[key], str):
                try:
                    result[key] = json.loads(result[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        return result

    async def update_proposal_status(self, proposal_id: str, status: str, **kwargs: Any) -> None:
        db = await self._conn()
        updates = {"status": status}
        updates.update(kwargs)
        set_clauses = ", ".join(f'"{k}" = ?' for k in updates.keys())
        sql = f"UPDATE change_proposal SET {set_clauses} WHERE proposal_id = ?"
        params = list(updates.values()) + [proposal_id]
        try:
            await db.execute(sql, params)
            await db.commit()
        except Exception as e:
            await db.rollback()
            raise StorageError(f"更新提案状态失败: {e}") from e

    async def insert_audit_log(self, log_entry: dict[str, Any]) -> None:
        db = await self._conn()
        row = dict(log_entry)
        for key in ("before_snapshot", "after_snapshot"):
            if key in row and row[key] is not None:
                row[key] = json.dumps(row[key], ensure_ascii=False, default=str)
        columns = list(row.keys())
        placeholders = ", ".join("?" for _ in columns)
        col_names = ", ".join(f'"{c}"' for c in columns)
        sql = f"INSERT INTO audit_log ({col_names}) VALUES ({placeholders})"
        try:
            await db.execute(sql, list(row.values()))
            await db.commit()
        except Exception as e:
            await db.rollback()
            raise StorageError(f"写入审计日志失败: {e}") from e

    async def insert_relation(self, relation: dict[str, Any]) -> dict[str, Any]:
        db = await self._conn()
        row = dict(relation)
        if "metadata" in row and row["metadata"] is not None:
            row["metadata"] = json.dumps(row["metadata"], ensure_ascii=False, default=str)
        columns = list(row.keys())
        placeholders = ", ".join("?" for _ in columns)
        col_names = ", ".join(f'"{c}"' for c in columns)
        sql = f"INSERT INTO object_relation ({col_names}) VALUES ({placeholders})"
        try:
            await db.execute(sql, list(row.values()))
            await db.commit()
        except Exception as e:
            await db.rollback()
            raise StorageError(f"插入关联失败: {e}") from e
        return relation

    async def get_relations(self, object_type: str, record_id: str) -> list[dict[str, Any]]:
        db = await self._conn()
        sql = (
            "SELECT * FROM object_relation "
            "WHERE (source_type = ? AND source_id = ?) OR (target_type = ? AND target_id = ?)"
        )
        cursor = await db.execute(sql, (object_type, record_id, object_type, record_id))
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d.get("metadata") and isinstance(d["metadata"], str):
                try:
                    d["metadata"] = json.loads(d["metadata"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(d)
        return results

    # ── Schema 审计日志查询 ──

    async def list_schema_audit_logs(self, limit: int = 20) -> list[dict[str, Any]]:
        """查询 schema 变更审计日志（record_id='__schema__'），按 changed_at 降序。"""
        db = await self._conn()
        cursor = await db.execute(
            "SELECT * FROM audit_log WHERE record_id = '__schema__' ORDER BY changed_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            d = dict(row)
            for key in ("before_snapshot", "after_snapshot"):
                if d.get(key) and isinstance(d[key], str):
                    try:
                        d[key] = json.loads(d[key])
                    except (json.JSONDecodeError, TypeError):
                        pass
            results.append(d)
        return results

    # ── 动态对象定义持久化 ──

    async def save_dynamic_definition(
        self, object_name: str, definition_json: str,
        workspace_id: str, created_by: str = "agent",
    ) -> None:
        """保存或更新动态对象定义"""
        db = await self._conn()
        now = _now_iso()
        try:
            await db.execute(
                """INSERT INTO dynamic_object_definitions
                   (object_name, definition_json, workspace_id, created_by, created_at, updated_at, schema_version, status)
                   VALUES (?, ?, ?, ?, ?, ?, 1, 'active')
                   ON CONFLICT(object_name) DO UPDATE SET
                     definition_json = excluded.definition_json,
                     updated_at = ?,
                     schema_version = schema_version + 1""",
                (object_name, definition_json, workspace_id, created_by, now, now, now),
            )
            await db.commit()
        except Exception as e:
            await db.rollback()
            raise StorageError(f"保存动态对象定义失败: {e}") from e

    async def get_dynamic_definition(self, object_name: str) -> dict[str, Any] | None:
        db = await self._conn()
        cursor = await db.execute(
            "SELECT * FROM dynamic_object_definitions WHERE object_name = ? AND status = 'active'",
            (object_name,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_dynamic_definitions(self) -> list[dict[str, Any]]:
        db = await self._conn()
        cursor = await db.execute(
            "SELECT * FROM dynamic_object_definitions WHERE status = 'active'"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def archive_dynamic_definition(self, object_name: str) -> None:
        """软删除动态对象定义"""
        db = await self._conn()
        now = _now_iso()
        try:
            await db.execute(
                "UPDATE dynamic_object_definitions SET status = 'archived', updated_at = ? WHERE object_name = ?",
                (now, object_name),
            )
            await db.commit()
        except Exception as e:
            await db.rollback()
            raise StorageError(f"归档动态对象定义失败: {e}") from e

    async def rebuild_table(
        self, object_name: str, old_columns: list[str],
        new_ddl: str, column_mapping: dict[str, str],
    ) -> int:
        """重建表实现字段类型变更。返回迁移的行数。"""
        db = await self._conn()
        table = object_name.lower()
        tmp_table = f"_tmp_{table}"
        try:
            # 1. 建新表
            await db.execute(new_ddl.replace(f'"{table}"', f'"{tmp_table}"'))
            # 2. 迁移数据
            src_cols = ", ".join(f'"{c}"' for c in old_columns if c in column_mapping)
            dst_cols = ", ".join(f'"{column_mapping[c]}"' for c in old_columns if c in column_mapping)
            cursor = await db.execute(
                f'INSERT INTO "{tmp_table}" ({dst_cols}) SELECT {src_cols} FROM "{table}"'
            )
            migrated = cursor.rowcount
            # 3. 替换
            await db.execute(f'DROP TABLE "{table}"')
            await db.execute(f'ALTER TABLE "{tmp_table}" RENAME TO "{table}"')
            await db.commit()
            return migrated
        except Exception as e:
            await db.rollback()
            raise StorageError(f"重建表失败: {e}") from e

    # ── 关闭连接 ──

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
