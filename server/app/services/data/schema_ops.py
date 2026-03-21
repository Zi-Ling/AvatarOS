"""
SchemaOps — schema 级操作处理器

处理 create_object / alter_object / drop_object 操作。
通过 data_propose / data_commit 统一入口调用。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from .models import (
    BASE_FIELDS,
    ChangeProposal,
    FieldDefinition,
    FieldType,
    InvalidProposalError,
    ObjectDefinition,
    ObjectNotFoundError,
    OperationType,
    ProposalStatus,
    RelationConstraint,
    UnsafeSchemaChangeError,
    is_safe_type_conversion,
    DuplicateObjectError,
)
from .registry import ObjectRegistry
from .storage import WorkflowStorage

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _field_from_dict(d: dict[str, Any]) -> FieldDefinition:
    """从 dict 构建 FieldDefinition"""
    ft = FieldType(d.get("type", "text"))
    return FieldDefinition(
        name=d["name"],
        field_type=ft,
        required=d.get("required", False),
        enum_values=d.get("enum_values"),
        reference_to=d.get("reference_to"),
        indexed=d.get("indexed", False),
        deprecated=d.get("deprecated", False),
        renamed_from=d.get("renamed_from"),
    )


def _definition_to_json(defn: ObjectDefinition) -> str:
    """序列化 ObjectDefinition 为 JSON"""
    return json.dumps({
        "name": defn.name,
        "description": defn.description,
        "schema_version": defn.schema_version,
        "fields": [
            {
                "name": f.name,
                "type": f.field_type.value,
                "required": f.required,
                **({"enum_values": f.enum_values} if f.enum_values else {}),
                **({"reference_to": f.reference_to} if f.reference_to else {}),
                **({"indexed": True} if f.indexed else {}),
                **({"deprecated": True} if f.deprecated else {}),
                **({"renamed_from": f.renamed_from} if f.renamed_from else {}),
            }
            for f in defn.fields
        ],
        "allowed_relations": [
            {"relation_type": r.relation_type, "target_type": r.target_type,
             "description": r.description}
            for r in defn.allowed_relations
        ],
    }, ensure_ascii=False)


def definition_from_json(data: str | dict) -> ObjectDefinition:
    """从 JSON 反序列化 ObjectDefinition"""
    if isinstance(data, str):
        data = json.loads(data)
    fields = [_field_from_dict(f) for f in data.get("fields", [])]
    relations = [
        RelationConstraint(
            relation_type=r["relation_type"],
            target_type=r["target_type"],
            description=r.get("description", ""),
        )
        for r in data.get("allowed_relations", [])
    ]
    return ObjectDefinition(
        name=data["name"],
        description=data.get("description", ""),
        schema_version=data.get("schema_version", 1),
        fields=fields,
        allowed_relations=relations,
    )


class SchemaOps:
    """Schema 级操作处理器"""

    def __init__(
        self,
        registry: ObjectRegistry,
        workflow_storage: WorkflowStorage,
        schema_storage: Any = None,
    ) -> None:
        self._registry = registry
        self._workflow = workflow_storage
        self._schema_storage = schema_storage

    # ── create_object ──

    async def propose_create_object(
        self,
        object_type: str,
        fields: list[dict[str, Any]],
        description: str = "",
        relations: list[dict[str, Any]] | None = None,
        workspace_id: str = "default",
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """创建新对象类型的提案"""
        # 校验：不能和已有对象重名
        if self._registry.get(object_type):
            raise DuplicateObjectError(f"对象类型已存在: {object_type}")

        if not fields:
            raise InvalidProposalError("创建对象至少需要一个业务字段")

        # 构建 ObjectDefinition
        field_defs = [_field_from_dict(f) for f in fields]
        relation_defs = [
            RelationConstraint(
                relation_type=r["relation_type"],
                target_type=r["target_type"],
                description=r.get("description", ""),
            )
            for r in (relations or [])
        ]
        defn = ObjectDefinition(
            name=object_type,
            fields=field_defs,
            description=description,
            schema_version=1,
            allowed_relations=relation_defs,
        )

        proposal_id = str(uuid.uuid4())
        now = _now_iso()
        changes = json.loads(_definition_to_json(defn))

        proposal = ChangeProposal(
            proposal_id=proposal_id,
            object_type=object_type,
            operation=OperationType.CREATE_OBJECT,
            record_id=None,
            changes=changes,
            summary=f"创建业务对象: {object_type} ({description})",
            diff_snapshot={"before": None, "after": changes},
            risk_level="low",
            status=ProposalStatus.PENDING,
            workspace_id=workspace_id,
            trace_id=trace_id,
            created_at=now,
        )

        from .proposal import ProposalService
        await self._workflow.insert_proposal(
            ProposalService._proposal_to_dict(proposal)
        )

        return {
            "proposal_id": proposal_id,
            "operation": "create_object",
            "object_type": object_type,
            "risk_level": "low",
            "preview": changes,
            "status": "pending",
        }


    # ── alter_object ──

    async def propose_alter_object(
        self,
        object_type: str,
        changes: dict[str, Any],
        workspace_id: str = "default",
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """修改已有对象的提案。

        changes 支持的 key:
          add_fields: list[dict]       — 新增字段
          add_relations: list[dict]    — 新增关联声明
          update_description: str      — 修改描述
          drop_field: str              — 软删除字段（标记 deprecated）
          change_field_type: dict      — 改字段类型 {field, new_type}
          rename_field: dict           — 重命名字段 {from, to}
        """
        defn = self._registry.get(object_type)
        if not defn:
            raise ObjectNotFoundError(f"对象类型不存在: {object_type}")

        if not self._registry.is_dynamic(object_type):
            raise InvalidProposalError(
                f"不能修改内置对象: {object_type}。"
                f"内置对象的 schema 变更需要通过代码升级实现。"
                f"如需扩展，请创建新的动态对象并建立关联。"
            )

        risk_level = "low"
        warnings: list[str] = []
        diff_before = _definition_to_json(defn)

        # 校验各操作
        if "change_field_type" in changes:
            ct = changes["change_field_type"]
            field_name = ct.get("field", "")
            new_type = ct.get("new_type", "")
            # 找到现有字段
            existing_field = next(
                (f for f in defn.fields if f.name == field_name), None
            )
            if not existing_field:
                raise InvalidProposalError(f"字段不存在: {field_name}")
            old_type = existing_field.field_type.value
            if not is_safe_type_conversion(old_type, new_type):
                raise UnsafeSchemaChangeError(
                    f"{old_type} → {new_type} 不安全：可能导致数据丢失。"
                    f"SQLite 不支持类型收窄操作。"
                    f"允许的安全转换方向：integer→float, integer→text, "
                    f"float→text, boolean→text, boolean→integer, "
                    f"datetime→text, enum→text, reference→text"
                )
            risk_level = "medium"
            warnings.append(f"字段 {field_name} 将从 {old_type} 转为 {new_type}，需要重建表")

        if "drop_field" in changes:
            field_name = changes["drop_field"]
            existing_field = next(
                (f for f in defn.fields if f.name == field_name), None
            )
            if not existing_field:
                raise InvalidProposalError(f"字段不存在: {field_name}")
            if existing_field.required:
                warnings.append(f"字段 {field_name} 是必填字段，标记废弃后新记录将不再要求此字段")
            risk_level = "medium"

        if "rename_field" in changes:
            rf = changes["rename_field"]
            old_name = rf.get("from", "")
            new_name = rf.get("to", "")
            if not any(f.name == old_name for f in defn.fields):
                raise InvalidProposalError(f"字段不存在: {old_name}")
            if any(f.name == new_name for f in defn.fields):
                raise InvalidProposalError(f"字段名已存在: {new_name}")
            risk_level = "medium"
            warnings.append(f"字段 {old_name} 将重命名为 {new_name}，需要重建表")

        if "add_fields" in changes:
            for fd in changes["add_fields"]:
                if any(f.name == fd["name"] for f in defn.fields):
                    raise InvalidProposalError(f"字段已存在: {fd['name']}")

        proposal_id = str(uuid.uuid4())
        now = _now_iso()

        proposal = ChangeProposal(
            proposal_id=proposal_id,
            object_type=object_type,
            operation=OperationType.ALTER_OBJECT,
            record_id=None,
            changes=changes,
            summary=f"修改业务对象: {object_type}",
            diff_snapshot={"before": json.loads(diff_before), "warnings": warnings},
            risk_level=risk_level,
            status=ProposalStatus.PENDING,
            workspace_id=workspace_id,
            trace_id=trace_id,
            created_at=now,
        )

        from .proposal import ProposalService
        await self._workflow.insert_proposal(
            ProposalService._proposal_to_dict(proposal)
        )

        result: dict[str, Any] = {
            "proposal_id": proposal_id,
            "operation": "alter_object",
            "object_type": object_type,
            "risk_level": risk_level,
            "changes": changes,
            "status": "pending",
        }
        if warnings:
            result["warnings"] = warnings
        return result


    # ── drop_object ──

    async def propose_drop_object(
        self,
        object_type: str,
        workspace_id: str = "default",
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """删除对象类型的提案（软删除）"""
        defn = self._registry.get(object_type)
        if not defn:
            raise ObjectNotFoundError(f"对象类型不存在: {object_type}")

        if not self._registry.is_dynamic(object_type):
            raise InvalidProposalError(
                f"不能删除内置对象: {object_type}。"
                f"内置对象（Contact/Task/Activity）是系统核心对象，不支持删除。"
            )

        # 统计影响范围
        impact: dict[str, Any] = {
            "field_count": len(defn.fields),
            "relation_count": len(defn.allowed_relations),
        }

        proposal_id = str(uuid.uuid4())
        now = _now_iso()
        changes = {"action": "archive_object"}

        proposal = ChangeProposal(
            proposal_id=proposal_id,
            object_type=object_type,
            operation=OperationType.DROP_OBJECT,
            record_id=None,
            changes=changes,
            summary=f"删除业务对象: {object_type}（软删除，数据保留）",
            diff_snapshot={"before": json.loads(_definition_to_json(defn)), "after": None},
            risk_level="high",
            status=ProposalStatus.PENDING,
            workspace_id=workspace_id,
            trace_id=trace_id,
            created_at=now,
        )

        from .proposal import ProposalService
        await self._workflow.insert_proposal(
            ProposalService._proposal_to_dict(proposal)
        )

        return {
            "proposal_id": proposal_id,
            "operation": "drop_object",
            "object_type": object_type,
            "risk_level": "high",
            "impact": impact,
            "note": "软删除：对象将被标记为归档，数据表保留不删除",
            "status": "pending",
        }

    # ── commit schema proposal ──

    async def commit_schema_proposal(
        self,
        proposal_id: str,
        approved_by: str = "agent",
    ) -> dict[str, Any]:
        """执行 schema 提案"""
        raw = await self._workflow.get_proposal(proposal_id)
        if raw is None:
            raise InvalidProposalError(f"提案不存在: {proposal_id}")

        status = raw["status"]
        if status != ProposalStatus.PENDING.value:
            raise InvalidProposalError(f"提案状态无效: {status}")

        op = OperationType(raw["operation"])
        object_type = raw["object_type"]
        changes = raw["changes"]
        workspace_id = raw["workspace_id"]
        now = _now_iso()

        if op == OperationType.CREATE_OBJECT:
            result = await self._commit_create_object(object_type, changes, workspace_id)
        elif op == OperationType.ALTER_OBJECT:
            result = await self._commit_alter_object(object_type, changes, workspace_id)
        elif op == OperationType.DROP_OBJECT:
            result = await self._commit_drop_object(object_type, workspace_id)
        else:
            raise InvalidProposalError(f"不是 schema 操作: {op.value}")

        # 更新提案状态
        await self._workflow.update_proposal_status(
            proposal_id,
            ProposalStatus.COMMITTED.value,
            approved_by=approved_by,
            approved_at=now,
        )

        # 审计日志
        from .models import AuditLogEntry
        audit = AuditLogEntry(
            change_id=str(uuid.uuid4()),
            object_type=object_type,
            record_id="__schema__",
            operation=op,
            before_snapshot=raw.get("diff_snapshot", {}).get("before"),
            after_snapshot=result,
            proposal_id=proposal_id,
            actor=approved_by,
            trace_id=raw.get("trace_id"),
            changed_at=now,
        )
        from .proposal import ProposalService
        await self._workflow.insert_audit_log(ProposalService._audit_to_dict(audit))

        return {
            "proposal_id": proposal_id,
            "status": "committed",
            "operation": op.value,
            "object_type": object_type,
            "result": result,
        }


    # ── commit 内部实现 ──

    async def _commit_create_object(
        self, object_type: str, changes: dict[str, Any], workspace_id: str,
    ) -> dict[str, Any]:
        """执行 create_object：注册 + 建表 + 持久化"""
        defn = definition_from_json(changes)

        # 注册到 registry
        self._registry.register_dynamic(defn)

        # 建表（通过 SchemaMigration）
        from .migration import SchemaMigration
        migrator = SchemaMigration()
        await migrator._create_table(self._schema_storage, defn)
        await self._schema_storage.set_schema_version(object_type, defn.schema_version)

        # 持久化动态定义
        await self._schema_storage.save_dynamic_definition(
            object_type, _definition_to_json(defn), workspace_id,
        )

        logger.info(f"[SchemaOps] 创建动态对象: {object_type} ({len(defn.fields)} 字段)")
        return {"object_type": object_type, "fields": len(defn.fields), "action": "created"}

    async def _commit_alter_object(
        self, object_type: str, changes: dict[str, Any], workspace_id: str,
    ) -> dict[str, Any]:
        """执行 alter_object：修改 schema + 迁移"""
        defn = self._registry.get(object_type)
        if not defn:
            raise ObjectNotFoundError(f"对象类型不存在: {object_type}")

        actions_done: list[str] = []
        needs_rebuild = False

        # 1. update_description
        if "update_description" in changes:
            defn.description = changes["update_description"]
            actions_done.append("updated_description")

        # 2. add_fields
        if "add_fields" in changes:
            new_fields = [_field_from_dict(f) for f in changes["add_fields"]]
            defn.fields.extend(new_fields)
            # ADD COLUMN
            stmts = []
            from .migration import _TYPE_MAP
            for f in new_fields:
                if f.field_type == FieldType.COMPUTED:
                    continue
                sql_type = _TYPE_MAP.get(f.field_type, "TEXT")
                table = object_type.lower()
                stmts.append(f'ALTER TABLE "{table}" ADD COLUMN "{f.name}" {sql_type}')
                if f.indexed:
                    stmts.append(
                        f'CREATE INDEX IF NOT EXISTS "idx_{table}_{f.name}" ON "{table}" ("{f.name}")'
                    )
            if stmts:
                await self._schema_storage.execute_ddl(stmts)
            actions_done.append(f"added_{len(new_fields)}_fields")

        # 3. add_relations
        if "add_relations" in changes:
            new_rels = [
                RelationConstraint(
                    relation_type=r["relation_type"],
                    target_type=r["target_type"],
                    description=r.get("description", ""),
                )
                for r in changes["add_relations"]
            ]
            defn.allowed_relations.extend(new_rels)
            actions_done.append(f"added_{len(new_rels)}_relations")

        # 4. drop_field (soft delete)
        if "drop_field" in changes:
            field_name = changes["drop_field"]
            for f in defn.fields:
                if f.name == field_name:
                    f.deprecated = True
                    f.required = False
                    break
            actions_done.append(f"deprecated_{field_name}")

        # 5. change_field_type (rebuild table)
        if "change_field_type" in changes:
            ct = changes["change_field_type"]
            field_name = ct["field"]
            new_type = ct["new_type"]
            for f in defn.fields:
                if f.name == field_name:
                    f.field_type = FieldType(new_type)
                    break
            needs_rebuild = True
            actions_done.append(f"changed_{field_name}_to_{new_type}")

        # 6. rename_field (rebuild table)
        if "rename_field" in changes:
            rf = changes["rename_field"]
            old_name, new_name = rf["from"], rf["to"]
            for f in defn.fields:
                if f.name == old_name:
                    f.renamed_from = old_name
                    f.name = new_name
                    break
            needs_rebuild = True
            actions_done.append(f"renamed_{old_name}_to_{new_name}")

        # 重建表（如果需要）
        if needs_rebuild:
            await self._rebuild_table_for_definition(object_type, defn)

        # 更新版本
        defn.schema_version += 1

        # 更新 registry
        self._registry.register_dynamic(defn)

        # 持久化
        await self._schema_storage.save_dynamic_definition(
            object_type, _definition_to_json(defn), workspace_id,
        )
        await self._schema_storage.set_schema_version(object_type, defn.schema_version)

        logger.info(f"[SchemaOps] 修改对象 {object_type}: {actions_done}")
        return {"object_type": object_type, "actions": actions_done}

    async def _commit_drop_object(
        self, object_type: str, workspace_id: str,
    ) -> dict[str, Any]:
        """执行 drop_object：软删除"""
        # 从 registry 注销
        self._registry.unregister(object_type)

        # 持久化标记归档
        await self._schema_storage.archive_dynamic_definition(object_type)

        logger.info(f"[SchemaOps] 归档动态对象: {object_type}")
        return {"object_type": object_type, "action": "archived"}

    async def _rebuild_table_for_definition(
        self, object_type: str, defn: ObjectDefinition,
    ) -> None:
        """通过重建表实现字段类型变更/重命名"""
        from .migration import SchemaMigration, _col_def
        table = object_type.lower()

        # 获取旧列
        old_columns = await self._schema_storage.get_table_columns(table)

        # 构建新表 DDL
        all_fields = list(BASE_FIELDS) + defn.fields
        col_defs: list[str] = []
        for f in all_fields:
            cd = _col_def(f, is_pk=(f.name == "id"))
            if cd:
                col_defs.append(cd)
        new_ddl = f'CREATE TABLE IF NOT EXISTS "{table}" (\n  ' + ",\n  ".join(col_defs) + "\n)"

        # 构建列映射（旧列名 → 新列名）
        column_mapping: dict[str, str] = {}
        rename_map: dict[str, str] = {}
        for f in all_fields:
            if f.field_type == FieldType.COMPUTED:
                continue
            if f.renamed_from and f.renamed_from in old_columns:
                rename_map[f.renamed_from] = f.name
            elif f.name in old_columns:
                column_mapping[f.name] = f.name

        # 合并 rename 映射
        column_mapping.update(rename_map)

        migrated = await self._schema_storage.rebuild_table(
            object_type, old_columns, new_ddl, column_mapping,
        )
        logger.info(f"[SchemaOps] 重建表 {table}: 迁移 {migrated} 行")
