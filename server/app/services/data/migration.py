"""
SchemaMigration — append-only schema 迁移管理

仅支持安全操作：CREATE TABLE、ALTER TABLE ADD COLUMN、CREATE INDEX IF NOT EXISTS。
不处理 rename、drop、type change。
连续执行两次结果幂等。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .models import BASE_FIELDS, FieldDefinition, FieldType, ObjectDefinition

if TYPE_CHECKING:
    from .storage import SchemaStorage

logger = logging.getLogger(__name__)

# FieldType → SQLite 列类型
_TYPE_MAP: dict[FieldType, str] = {
    FieldType.TEXT: "TEXT",
    FieldType.INTEGER: "INTEGER",
    FieldType.FLOAT: "REAL",
    FieldType.BOOLEAN: "INTEGER",  # SQLite 无原生 bool
    FieldType.DATETIME: "TEXT",  # ISO 8601
    FieldType.ENUM: "TEXT",
    FieldType.REFERENCE: "TEXT",  # 存储目标 record_id
    # COMPUTED 不建列
}


def _col_def(field: FieldDefinition, is_pk: bool = False) -> str | None:
    """生成单个列的 DDL 片段，COMPUTED 字段返回 None"""
    if field.field_type == FieldType.COMPUTED:
        return None
    sql_type = _TYPE_MAP.get(field.field_type, "TEXT")
    parts = [f'"{field.name}" {sql_type}']
    if is_pk:
        parts.append("PRIMARY KEY")
    elif field.required:
        parts.append("NOT NULL")
    if field.name == "version":
        parts.append("DEFAULT 1")
    return " ".join(parts)


class SchemaMigration:
    """Schema 版本管理与增量迁移"""

    async def check_and_migrate(
        self,
        storage: SchemaStorage,
        definitions: list[ObjectDefinition],
    ) -> None:
        """
        对比 ObjectDefinition.schema_version 与数据库 schema_version，
        执行必要的 DDL 操作。幂等：连续执行两次结果一致。
        """
        for defn in definitions:
            table = defn.name.lower()
            db_version = await storage.get_schema_version(defn.name)

            if db_version is None:
                # 表不存在，全量建表
                await self._create_table(storage, defn)
                await storage.set_schema_version(defn.name, defn.schema_version)
                logger.info(f"创建表 {table}，schema_version={defn.schema_version}")
            elif db_version < defn.schema_version:
                # 增量迁移：加列 + 加索引
                await self._migrate_table(storage, defn)
                await storage.set_schema_version(defn.name, defn.schema_version)
                logger.info(f"迁移表 {table}: v{db_version} → v{defn.schema_version}")
            else:
                logger.debug(f"表 {table} 已是最新版本 v{db_version}")

    async def _create_table(self, storage: SchemaStorage, defn: ObjectDefinition) -> None:
        """全量建表"""
        table = defn.name.lower()
        all_fields = list(BASE_FIELDS) + defn.fields
        col_defs: list[str] = []
        for f in all_fields:
            cd = _col_def(f, is_pk=(f.name == "id"))
            if cd:
                col_defs.append(cd)

        create_sql = f'CREATE TABLE IF NOT EXISTS "{table}" (\n  ' + ",\n  ".join(col_defs) + "\n)"
        stmts = [create_sql]

        # 索引
        for f in defn.fields:
            if f.indexed and f.field_type != FieldType.COMPUTED:
                stmts.append(
                    f'CREATE INDEX IF NOT EXISTS "idx_{table}_{f.name}" ON "{table}" ("{f.name}")'
                )
        # workspace_id 索引（所有表都需要）
        stmts.append(
            f'CREATE INDEX IF NOT EXISTS "idx_{table}_workspace_id" ON "{table}" ("workspace_id")'
        )

        await storage.execute_ddl(stmts)

    async def _migrate_table(self, storage: SchemaStorage, defn: ObjectDefinition) -> None:
        """增量迁移：对比现有列，ADD COLUMN + CREATE INDEX"""
        table = defn.name.lower()
        existing_cols = set(await storage.get_table_columns(table))

        stmts: list[str] = []
        all_fields = list(BASE_FIELDS) + defn.fields
        for f in all_fields:
            if f.field_type == FieldType.COMPUTED:
                continue
            if f.name not in existing_cols:
                sql_type = _TYPE_MAP.get(f.field_type, "TEXT")
                stmts.append(f'ALTER TABLE "{table}" ADD COLUMN "{f.name}" {sql_type}')
                logger.info(f"增量加列: {table}.{f.name} ({sql_type})")

        # 索引
        for f in defn.fields:
            if f.indexed and f.field_type != FieldType.COMPUTED:
                stmts.append(
                    f'CREATE INDEX IF NOT EXISTS "idx_{table}_{f.name}" ON "{table}" ("{f.name}")'
                )

        if stmts:
            await storage.execute_ddl(stmts)
