"""
DataService — 数据层核心服务

读操作、派生字段计算、对象元数据描述。
提案操作委托给 ProposalService。
workspace 强制隔离：所有读写操作强制注入 workspace_id。
"""

from __future__ import annotations

import logging
from typing import Any

from .models import (
    DataErrorCode,
    FilterCondition,
    FilterOperator,
    InvalidFieldError,
    ObjectNotFoundError,
    RecordNotFoundError,
    WorkspaceMismatchError,
)
from .migration import SchemaMigration
from .proposal import ProposalService
from .registry import ObjectRegistry
from .storage import RecordStorage, SchemaStorage, WorkflowStorage

logger = logging.getLogger(__name__)


# ── 内置派生字段计算器 ──

async def _compute_contact_last_activity_at(
    record: dict[str, Any], record_storage: RecordStorage
) -> Any:
    """Contact 最近活动时间：关联 Activity 中最大的 occurred_at"""
    contact_id = record.get("id")
    if not contact_id:
        return None
    try:
        filters = [FilterCondition(field="related_contact_id", operator=FilterOperator.EQ, value=contact_id)]
        activities, _ = await record_storage.list_records(
            "Activity", filters, sort_by="occurred_at", sort_order="desc",
            offset=0, limit=1, include_archived=False,
        )
        if activities:
            return activities[0].get("occurred_at")
    except Exception:
        pass
    return None


async def _compute_contact_open_task_count(
    record: dict[str, Any], record_storage: RecordStorage
) -> Any:
    """Contact 未完成任务数：关联的未归档 Task 数量"""
    contact_id = record.get("id")
    if not contact_id:
        return 0
    try:
        filters = [FilterCondition(field="related_contact_id", operator=FilterOperator.EQ, value=contact_id)]
        _, total = await record_storage.list_records(
            "Task", filters, sort_by=None, sort_order="asc",
            offset=0, limit=0, include_archived=False,
        )
        return total
    except Exception:
        return 0


# compute_key → 计算函数映射
_COMPUTE_REGISTRY: dict[str, Any] = {
    "contact_last_activity_at": _compute_contact_last_activity_at,
    "contact_open_task_count": _compute_contact_open_task_count,
}


class DataService:
    """数据层核心服务：读操作、派生字段、对象元数据"""

    def __init__(
        self,
        registry: ObjectRegistry,
        record_storage: RecordStorage,
        proposal_service: ProposalService,
        schema_storage: SchemaStorage | None = None,
        workflow_storage: WorkflowStorage | None = None,
    ) -> None:
        self._registry = registry
        self._records = record_storage
        self._proposals = proposal_service
        self._schema_storage = schema_storage
        self._workflow = workflow_storage
        self._migration = SchemaMigration()

    async def initialize(self) -> None:
        """初始化存储（backend.initialize + schema migration + 加载动态对象）"""
        if self._schema_storage:
            await self._schema_storage.initialize()
            definitions = self._registry.list_all()
            await self._migration.check_and_migrate(self._schema_storage, definitions)
            # 加载动态对象定义
            await self._load_dynamic_objects()
            logger.info("DataService 初始化完成")

    async def _load_dynamic_objects(self) -> None:
        """从持久化存储加载动态对象定义并注册到 registry"""
        if not self._schema_storage:
            return
        try:
            rows = await self._schema_storage.list_dynamic_definitions()
            for row in rows:
                try:
                    from .schema_ops import definition_from_json
                    defn = definition_from_json(row["definition_json"])
                    self._registry.register_dynamic(defn)
                    # 确保表存在
                    await self._migration.check_and_migrate(
                        self._schema_storage, [defn]
                    )
                    logger.info(f"加载动态对象: {defn.name} (v{defn.schema_version})")
                except Exception as e:
                    logger.warning(f"加载动态对象 {row.get('object_name')} 失败: {e}")
        except Exception as e:
            logger.warning(f"加载动态对象列表失败: {e}")

    # ── 读操作（强制 workspace_id） ──

    async def list_records(
        self,
        object_type: str,
        workspace_id: str,
        filters: list[FilterCondition] | None = None,
        sort_by: str | None = None,
        sort_order: str = "asc",
        offset: int = 0,
        limit: int = 50,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        """列表查询，自动注入 workspace_id 过滤"""
        defn = self._registry.get(object_type)
        if not defn:
            raise ObjectNotFoundError(f"对象类型不存在: {object_type}")

        # 校验 filter 字段名
        all_filters = list(filters or [])
        all_field_names = {f.name for f in self._registry.get_all_fields(object_type)}
        for fc in all_filters:
            if fc.field not in all_field_names:
                raise InvalidFieldError(f"字段不存在: {fc.field}")

        # 强制注入 workspace_id
        all_filters.append(
            FilterCondition(field="workspace_id", operator=FilterOperator.EQ, value=workspace_id)
        )

        # 校验 sort_by
        if sort_by and sort_by not in all_field_names:
            raise InvalidFieldError(f"排序字段不存在: {sort_by}")

        records, total = await self._records.list_records(
            object_type, all_filters, sort_by, sort_order, offset, limit, include_archived
        )

        # 填充派生字段
        for rec in records:
            await self._fill_computed_fields(object_type, rec)

        return {"records": records, "total": total, "offset": offset, "limit": limit}

    async def get_record(
        self,
        object_type: str,
        record_id: str,
        workspace_id: str,
        include_relations: bool = False,
    ) -> dict[str, Any]:
        """单条查询，校验 workspace_id 归属"""
        defn = self._registry.get(object_type)
        if not defn:
            raise ObjectNotFoundError(f"对象类型不存在: {object_type}")

        record = await self._records.get_by_id(object_type, record_id)
        if record is None:
            raise RecordNotFoundError(f"记录不存在: {record_id}")

        if record.get("workspace_id") != workspace_id:
            raise WorkspaceMismatchError(f"无权访问该记录")

        await self._fill_computed_fields(object_type, record)

        if include_relations and self._workflow:
            relations = await self._workflow.get_relations(object_type, record_id)
            # 按 relation_type 分组
            grouped: dict[str, list[dict[str, Any]]] = {}
            for rel in relations:
                rt = rel.get("relation_type", "unknown")
                grouped.setdefault(rt, []).append(rel)
            record["relations"] = grouped

        return record

    async def search_records(
        self,
        object_type: str,
        keyword: str,
        workspace_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """关键词搜索（仅 keyword 模式）"""
        defn = self._registry.get(object_type)
        if not defn:
            raise ObjectNotFoundError(f"对象类型不存在: {object_type}")

        text_fields = self._registry.get_text_fields(object_type)
        # search_text 内部已排除 archived，但不含 workspace 过滤
        # 我们在结果中过滤 workspace（search_text 是 LIKE 搜索，无法注入 workspace 条件到 OR 子句）
        # 改为：先搜索再过滤 workspace
        records, _ = await self._records.search_text(
            object_type, keyword, text_fields, offset=0, limit=1000
        )
        # workspace 过滤
        filtered = [r for r in records if r.get("workspace_id") == workspace_id]
        total = len(filtered)
        page = filtered[offset: offset + limit]

        for rec in page:
            await self._fill_computed_fields(object_type, rec)

        return {"records": page, "total": total, "offset": offset, "limit": limit}

    async def describe_objects(self) -> dict[str, Any]:
        """返回所有对象元数据（供 Planner schema grounding）"""
        result: list[dict[str, Any]] = []
        for defn in self._registry.list_all():
            fields_info = []
            for f in self._registry.get_all_fields(defn.name):
                info: dict[str, Any] = {
                    "name": f.name,
                    "type": f.field_type.value,
                    "required": f.required,
                }
                if f.enum_values:
                    info["enum_values"] = f.enum_values
                if f.reference_to:
                    info["reference_to"] = f.reference_to
                if f.readonly:
                    info["readonly"] = True
                if f.compute_key:
                    info["compute_key"] = f.compute_key
                if f.deprecated:
                    info["deprecated"] = True
                fields_info.append(info)

            relations_info = [
                {
                    "relation_type": r.relation_type,
                    "target_type": r.target_type,
                    "description": r.description,
                }
                for r in defn.allowed_relations
            ]

            result.append({
                "name": defn.name,
                "description": defn.description,
                "schema_version": defn.schema_version,
                "is_dynamic": self._registry.is_dynamic(defn.name),
                "fields": fields_info,
                "allowed_relations": relations_info,
            })

        return {
            "objects": result,
            "schema_operations": {
                "description": "通过 data_propose 管理对象 schema，data_commit 执行提案",
                "available_operations": [
                    {
                        "operation": "create_object",
                        "description": "创建新业务对象（建表）",
                        "required_params": ["object_type", "fields"],
                        "optional_params": ["object_description", "relations"],
                        "risk_level": "low",
                    },
                    {
                        "operation": "alter_object",
                        "description": "修改已有对象（加字段/改类型/重命名/软删除字段）",
                        "required_params": ["object_type", "changes"],
                        "changes_keys": ["add_fields", "drop_field", "change_field_type", "rename_field", "add_relations", "update_description"],
                        "risk_level": "medium",
                        "note": "仅动态对象可完全修改；内置对象仅支持加字段",
                    },
                    {
                        "operation": "drop_object",
                        "description": "删除动态对象（软删除，数据保留）",
                        "required_params": ["object_type"],
                        "risk_level": "high",
                        "note": "仅动态对象可删除，内置对象不可删除",
                    },
                ],
            },
        }


    # ── 提案操作委托 ──

    async def create_proposal(self, **kwargs: Any) -> dict[str, Any]:
        return await self._proposals.create_proposal(**kwargs)

    async def commit_proposal(self, **kwargs: Any) -> dict[str, Any]:
        return await self._proposals.commit_proposal(**kwargs)

    async def preview(self, **kwargs: Any) -> dict[str, Any]:
        return await self._proposals.preview(**kwargs)

    # ── 派生字段计算 ──

    async def _fill_computed_fields(self, object_type: str, record: dict[str, Any]) -> None:
        """为记录填充派生字段值"""
        computed = self._registry.get_computed_fields(object_type)
        for f in computed:
            if f.compute_key and f.compute_key in _COMPUTE_REGISTRY:
                value = await _COMPUTE_REGISTRY[f.compute_key](record, self._records)
                record[f.name] = value

    # ── 属性访问 ──

    @property
    def registry(self) -> ObjectRegistry:
        return self._registry

    @property
    def proposal_service(self) -> ProposalService:
        return self._proposals
