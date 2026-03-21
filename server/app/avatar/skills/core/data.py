"""
Data Skills — 结构化数据层技能

4 个 Skill，按"了解 → 查 → 提议 → 确认"划分：
- data_describe: 元数据发现
- data_query: 统一查询（record_id / keyword / filters）
- data_propose: 变更提案（create/update/archive/link）
- data_commit: 执行提案
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import Field

from ..base import BaseSkill, SkillSpec, SideEffect, SkillRiskLevel
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext
from app.avatar.runtime.graph.models.output_contract import (
    SkillOutputContract, ValueKind, TransportMode,
)

logger = logging.getLogger(__name__)


async def _get_data_service():
    """延迟导入 + 确保异步初始化（子进程中也能自动建表）"""
    from app.services.data import ensure_initialized
    return await ensure_initialized()


# ── 错误码 → 双语文案映射 ──

_ERROR_MESSAGES: dict[str, tuple[str, str]] = {
    "OBJECT_NOT_FOUND": ("对象类型不存在", "Object type not found"),
    "RECORD_NOT_FOUND": ("记录不存在", "Record not found"),
    "VERSION_CONFLICT": ("版本冲突，请刷新后重试", "Version conflict, please refresh"),
    "INVALID_PROPOSAL": ("提案无效", "Invalid proposal"),
    "PROPOSAL_EXPIRED": ("提案已过期", "Proposal expired"),
    "PROPOSAL_ALREADY_COMMITTED": ("提案已提交，不可重复执行", "Proposal already committed"),
    "VALIDATION_ERROR": ("字段校验失败", "Validation error"),
    "INVALID_FIELD": ("字段不存在", "Invalid field"),
    "READONLY_FIELD": ("字段为只读", "Readonly field"),
    "INVALID_RELATION": ("不允许的关联类型", "Invalid relation type"),
    "STORAGE_ERROR": ("存储操作失败，请稍后重试", "Storage error, please retry"),
    "WORKSPACE_MISMATCH": ("无权访问该记录", "Access denied"),
    "UNSAFE_SCHEMA_CHANGE": ("不安全的 schema 变更，可能导致数据丢失", "Unsafe schema change, may cause data loss"),
    "DUPLICATE_OBJECT": ("对象类型已存在", "Object type already exists"),
}


def _error_output(cls, e: Exception, **extra) -> SkillOutput:
    """将 DataError/异常转换为 SkillOutput(success=False)"""
    err_name = type(e).__name__
    # 从异常类名推断错误码
    code_map = {
        "ObjectNotFoundError": "OBJECT_NOT_FOUND",
        "RecordNotFoundError": "RECORD_NOT_FOUND",
        "VersionConflictError": "VERSION_CONFLICT",
        "InvalidProposalError": "INVALID_PROPOSAL",
        "ValidationError": "VALIDATION_ERROR",
        "InvalidFieldError": "INVALID_FIELD",
        "ReadonlyFieldError": "READONLY_FIELD",
        "StorageError": "STORAGE_ERROR",
        "WorkspaceMismatchError": "WORKSPACE_MISMATCH",
        "UnsafeSchemaChangeError": "UNSAFE_SCHEMA_CHANGE",
        "DuplicateObjectError": "DUPLICATE_OBJECT",
    }
    code = code_map.get(err_name, "STORAGE_ERROR")
    zh, en = _ERROR_MESSAGES.get(code, ("操作失败", "Operation failed"))
    msg = f"{zh} / {en}: {e}"
    return cls(success=False, message=msg, retryable=(code == "STORAGE_ERROR"), **extra)


# ── data_describe ──


class DataDescribeInput(SkillInput):
    pass  # 无参数


class DataDescribeOutput(SkillOutput):
    output: Optional[Any] = Field(None, description="对象元数据列表")


@register_skill
class DataDescribeSkill(BaseSkill[DataDescribeInput, DataDescribeOutput]):
    spec = SkillSpec(
        name="data_describe",
        description="Discover available business objects, their fields, enum values, and relations. "
                    "发现可用的业务对象、字段定义、枚举值和关联关系。",
        input_model=DataDescribeInput,
        output_model=DataDescribeOutput,
        side_effects={SideEffect.DATA_READ},
        risk_level=SkillRiskLevel.READ,
        aliases=["describe_data", "data_schema", "list_objects"],
        tags=["data", "describe", "schema", "metadata", "数据", "描述", "元数据", "对象"],
        output_contract=SkillOutputContract(value_kind=ValueKind.JSON, transport_mode=TransportMode.INLINE),
    )

    async def run(self, ctx: SkillContext, params: DataDescribeInput) -> DataDescribeOutput:
        if ctx.dry_run:
            return DataDescribeOutput(success=True, message="[dry_run] Would describe objects", output=None)
        try:
            svc = await _get_data_service()
            result = await svc.describe_objects()
            return DataDescribeOutput(success=True, message="对象元数据查询成功", output=result)
        except Exception as e:
            return _error_output(DataDescribeOutput, e)


# ── data_query ──


class DataQueryInput(SkillInput):
    object_type: str = Field(..., description="业务对象类型名（如 Contact、Task、Activity）")
    record_id: Optional[str] = Field(None, description="单条查询：记录 ID")
    keyword: Optional[str] = Field(None, description="关键词搜索")
    search_mode: str = Field("keyword", description="搜索模式: keyword/semantic（MVP 仅支持 keyword）")
    filters: Optional[list[dict[str, Any]]] = Field(None, description="条件过滤列表 [{field, operator, value}]")
    sort_by: Optional[str] = Field(None, description="排序字段")
    sort_order: str = Field("asc", description="排序方向 asc/desc")
    offset: int = Field(0, description="分页偏移")
    limit: int = Field(50, description="分页大小")
    include_archived: bool = Field(False, description="是否包含已归档记录")
    include_relations: bool = Field(False, description="是否包含关联记录摘要")


class DataQueryOutput(SkillOutput):
    output: Optional[Any] = Field(None, description="查询结果")


@register_skill
class DataQuerySkill(BaseSkill[DataQueryInput, DataQueryOutput]):
    spec = SkillSpec(
        name="data_query",
        description="Unified query: single record (record_id), keyword search (keyword), or filtered list (filters). "
                    "统一查询：单条(record_id)、关键词搜索(keyword)、条件列表(filters)。",
        input_model=DataQueryInput,
        output_model=DataQueryOutput,
        side_effects={SideEffect.DATA_READ},
        risk_level=SkillRiskLevel.READ,
        aliases=["query_data", "data_list", "data_get", "data_search"],
        tags=["data", "query", "list", "get", "search", "数据", "查询", "搜索", "列表"],
        output_contract=SkillOutputContract(value_kind=ValueKind.JSON, transport_mode=TransportMode.INLINE),
    )

    async def run(self, ctx: SkillContext, params: DataQueryInput) -> DataQueryOutput:
        if ctx.dry_run:
            return DataQueryOutput(success=True, message="[dry_run] Would query data", output=None)
        try:
            svc = await _get_data_service()
            workspace_id = ctx.execution_context.workspace_id if ctx.execution_context else "default"

            # 优先级：record_id > keyword > filters
            if params.record_id:
                record = await svc.get_record(
                    params.object_type, params.record_id, workspace_id,
                    include_relations=params.include_relations,
                )
                return DataQueryOutput(success=True, message="查询成功", output=record)

            if params.keyword:
                # search_mode 校验
                if params.search_mode == "semantic":
                    return DataQueryOutput(
                        success=False,
                        message="语义搜索功能尚未启用 / Semantic search not yet available",
                        output=None,
                    )
                result = await svc.search_records(
                    params.object_type, params.keyword, workspace_id,
                    offset=params.offset, limit=params.limit,
                )
                # 为每条记录添加 relevance_score（keyword 模式下为 1.0 固定值）
                for rec in result.get("records", []):
                    rec["relevance_score"] = 1.0
                return DataQueryOutput(success=True, message="搜索成功", output=result)

            # filters 模式（默认）
            from app.services.data.models import FilterCondition, FilterOperator
            filter_list = []
            if params.filters:
                for f in params.filters:
                    # 防御性检查：拒绝嵌套/OR 查询
                    if "logic" in f or "conditions" in f:
                        return DataQueryOutput(
                            success=False,
                            message="当前版本不支持此查询复杂度 / Unsupported query complexity in current version",
                            output=None,
                        )
                    filter_list.append(FilterCondition(
                        field=f["field"],
                        operator=FilterOperator(f["operator"]),
                        value=f.get("value"),
                    ))

            result = await svc.list_records(
                params.object_type, workspace_id,
                filters=filter_list if filter_list else None,
                sort_by=params.sort_by, sort_order=params.sort_order,
                offset=params.offset, limit=params.limit,
                include_archived=params.include_archived,
            )
            return DataQueryOutput(success=True, message="查询成功", output=result)

        except Exception as e:
            return _error_output(DataQueryOutput, e)


# ── data_propose ──


class DataProposeInput(SkillInput):
    object_type: str = Field(..., description="业务对象类型名")
    operation: str = Field(
        ...,
        description="操作类型: create/update/archive/link/create_object/alter_object/drop_object",
    )
    changes: Optional[dict[str, Any]] = Field(None, description="字段变更内容（create/update/alter_object 时）")
    summary: str = Field("", description="变更摘要")
    record_id: Optional[str] = Field(None, description="目标记录 ID（update/archive 时）")
    expected_version: Optional[int] = Field(None, description="乐观锁版本号（update/archive 时）")
    # link 操作参数
    relation_type: Optional[str] = Field(None, description="关联类型（link 时）")
    source_type: Optional[str] = Field(None, description="源对象类型（link 时）")
    source_id: Optional[str] = Field(None, description="源记录 ID（link 时）")
    target_type: Optional[str] = Field(None, description="目标对象类型（link 时）")
    target_id: Optional[str] = Field(None, description="目标记录 ID（link 时）")
    # schema 操作参数（create_object/alter_object）
    fields: Optional[list[dict[str, Any]]] = Field(None, description="字段定义列表（create_object 时）")
    object_description: Optional[str] = Field(None, description="对象描述（create_object 时）")
    relations: Optional[list[dict[str, Any]]] = Field(None, description="关联声明列表（create_object 时）")


class DataProposeOutput(SkillOutput):
    output: Optional[Any] = Field(None, description="提案详情")


@register_skill
class DataProposeSkill(BaseSkill[DataProposeInput, DataProposeOutput]):
    spec = SkillSpec(
        name="data_propose",
        description="Create a change proposal for business objects or schema operations. "
                    "Record ops: create/update/archive/link. "
                    "Schema ops: create_object/alter_object/drop_object. "
                    "创建业务对象变更提案或 schema 操作提案。",
        input_model=DataProposeInput,
        output_model=DataProposeOutput,
        side_effects={SideEffect.DATA_WRITE},
        risk_level=SkillRiskLevel.WRITE,
        aliases=["propose_data", "data_create", "data_update", "data_archive", "data_link",
                 "data_schema_propose", "create_table", "alter_table", "drop_table"],
        tags=["data", "propose", "create", "update", "archive", "link", "schema",
              "数据", "提案", "新建", "更新", "归档", "关联", "建表", "改表", "删表"],
        output_contract=SkillOutputContract(value_kind=ValueKind.JSON, transport_mode=TransportMode.INLINE),
    )

    async def run(self, ctx: SkillContext, params: DataProposeInput) -> DataProposeOutput:
        if ctx.dry_run:
            # schema 操作的 dry_run：直接返回操作预览，不落库
            if params.operation in ("create_object", "alter_object", "drop_object"):
                return DataProposeOutput(
                    success=True,
                    message=f"[dry_run] Would {params.operation} on {params.object_type}",
                    output={"operation": params.operation, "object_type": params.object_type},
                )
            try:
                svc = await _get_data_service()
                result = await svc.preview(
                    object_type=params.object_type,
                    operation=params.operation,
                    changes=params.changes or {},
                    record_id=params.record_id,
                    expected_version=params.expected_version,
                )
                return DataProposeOutput(success=True, message="[dry_run] 预览结果", output=result)
            except Exception as e:
                return _error_output(DataProposeOutput, e)
        try:
            svc = await _get_data_service()
            workspace_id = ctx.execution_context.workspace_id if ctx.execution_context else "default"
            trace_id = ctx.execution_context.session_id if ctx.execution_context else None

            # Schema 操作路由
            if params.operation in ("create_object", "alter_object", "drop_object"):
                return await self._handle_schema_op(svc, params, workspace_id, trace_id)

            if params.operation == "link":
                # link 操作：直接创建关联
                return await self._handle_link(svc, params, workspace_id)

            result = await svc.create_proposal(
                object_type=params.object_type,
                operation=params.operation,
                changes=params.changes or {},
                summary=params.summary,
                workspace_id=workspace_id,
                record_id=params.record_id,
                expected_version=params.expected_version,
                trace_id=trace_id,
            )
            return DataProposeOutput(success=True, message="提案创建成功", output=result)

        except Exception as e:
            return _error_output(DataProposeOutput, e)

    async def _handle_schema_op(
        self, svc, params: DataProposeInput, workspace_id: str, trace_id: str | None,
    ) -> DataProposeOutput:
        """路由 schema 操作到 SchemaOps"""
        from app.services.data.schema_ops import SchemaOps

        schema_ops = SchemaOps(
            registry=svc.registry,
            workflow_storage=svc._proposals._workflow,
            schema_storage=svc._proposals._schema_storage,
        )

        if params.operation == "create_object":
            if not params.fields:
                return DataProposeOutput(
                    success=False,
                    message="创建对象需要 fields 字段定义 / create_object requires fields",
                    output=None,
                )
            result = await schema_ops.propose_create_object(
                object_type=params.object_type,
                fields=params.fields,
                description=params.object_description or "",
                relations=params.relations,
                workspace_id=workspace_id,
                trace_id=trace_id,
            )
        elif params.operation == "alter_object":
            if not params.changes:
                return DataProposeOutput(
                    success=False,
                    message="修改对象需要 changes 变更内容 / alter_object requires changes",
                    output=None,
                )
            result = await schema_ops.propose_alter_object(
                object_type=params.object_type,
                changes=params.changes,
                workspace_id=workspace_id,
                trace_id=trace_id,
            )
        else:  # drop_object
            result = await schema_ops.propose_drop_object(
                object_type=params.object_type,
                workspace_id=workspace_id,
                trace_id=trace_id,
            )

        return DataProposeOutput(success=True, message="Schema 提案创建成功", output=result)

    async def _handle_link(
        self, svc, params: DataProposeInput, workspace_id: str
    ) -> DataProposeOutput:
        """处理 link 操作"""
        import uuid
        from datetime import datetime, timezone
        from app.services.data.models import InvalidProposalError

        if not all([params.relation_type, params.source_type, params.source_id,
                     params.target_type, params.target_id]):
            raise InvalidProposalError("link 操作需要 relation_type, source_type, source_id, target_type, target_id")

        # 校验关联约束
        allowed = svc.registry.get_allowed_relations(params.source_type)
        valid = any(
            r.relation_type == params.relation_type and r.target_type == params.target_type
            for r in allowed
        )
        if not valid:
            from app.services.data.models import InvalidFieldError
            raise InvalidFieldError(
                f"不允许的关联: {params.source_type}.{params.relation_type} → {params.target_type}"
            )

        # 直接创建关联（link 不走提案流程）
        relation = {
            "relation_id": str(uuid.uuid4()),
            "relation_type": params.relation_type,
            "source_type": params.source_type,
            "source_id": params.source_id,
            "target_type": params.target_type,
            "target_id": params.target_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        # 需要直接访问 workflow storage
        from app.services.data import ensure_initialized
        ds = await ensure_initialized()
        await ds._proposals._workflow.insert_relation(relation)
        return DataProposeOutput(success=True, message="关联创建成功", output=relation)


# ── data_commit ──


class DataCommitInput(SkillInput):
    proposal_id: str = Field(..., description="提案 ID")
    approver_id: Optional[str] = Field(None, description="审批者身份标识（预留，MVP 不做强制校验）")


class DataCommitOutput(SkillOutput):
    output: Optional[Any] = Field(None, description="提交结果")


@register_skill
class DataCommitSkill(BaseSkill[DataCommitInput, DataCommitOutput]):
    spec = SkillSpec(
        name="data_commit",
        description="Commit an approved change proposal. 执行已确认的变更提案。",
        input_model=DataCommitInput,
        output_model=DataCommitOutput,
        side_effects={SideEffect.DATA_WRITE},
        risk_level=SkillRiskLevel.WRITE,
        aliases=["commit_data", "execute_proposal", "confirm_proposal"],
        tags=["data", "commit", "execute", "confirm", "数据", "提交", "执行", "确认"],
        output_contract=SkillOutputContract(value_kind=ValueKind.JSON, transport_mode=TransportMode.INLINE),
    )

    async def run(self, ctx: SkillContext, params: DataCommitInput) -> DataCommitOutput:
        if ctx.dry_run:
            return DataCommitOutput(success=True, message="[dry_run] Would commit proposal", output=None)
        try:
            svc = await _get_data_service()
            trace_id = ctx.execution_context.session_id if ctx.execution_context else None
            approved_by = params.approver_id or "agent"
            result = await svc.commit_proposal(
                proposal_id=params.proposal_id,
                approved_by=approved_by,
                trace_id=trace_id,
            )
            return DataCommitOutput(success=True, message="提案执行成功", output=result)
        except Exception as e:
            return _error_output(DataCommitOutput, e)
