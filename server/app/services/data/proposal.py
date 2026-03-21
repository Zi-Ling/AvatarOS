"""
ProposalService — 提案生命周期管理

create_proposal: 创建变更提案（验证字段、生成 diff、计算 risk_level）
commit_proposal: 执行已批准的提案（幂等保护）
preview: 只计算 diff/risk 不落库
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from .models import (
    AuditLogEntry,
    ChangeProposal,
    DataErrorCode,
    InvalidProposalError,
    ObjectNotFoundError,
    OperationType,
    ProposalStatus,
    ReadonlyFieldError,
    RecordNotFoundError,
    ValidationError,
    VersionConflictError,
)
from .registry import ObjectRegistry
from .storage import RecordStorage, WorkflowStorage

logger = logging.getLogger(__name__)

# 高风险关键字段
_HIGH_RISK_FIELDS = frozenset({"priority", "stage", "assigned_to", "task_type"})


def _compute_risk_level(operation: OperationType, changes: dict[str, Any]) -> str:
    """计算风险等级：low / high"""
    if operation == OperationType.ARCHIVE:
        return "high"
    if operation == OperationType.UPDATE:
        if len(changes) > 5:
            return "high"
        if any(k in _HIGH_RISK_FIELDS for k in changes):
            return "high"
    return "low"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProposalService:
    """提案生命周期管理"""

    def __init__(
        self,
        registry: ObjectRegistry,
        record_storage: RecordStorage,
        workflow_storage: WorkflowStorage,
        schema_storage: Any = None,
    ) -> None:
        self._registry = registry
        self._records = record_storage
        self._workflow = workflow_storage
        self._schema_storage = schema_storage


    async def create_proposal(
        self,
        object_type: str,
        operation: str,
        changes: dict[str, Any],
        summary: str,
        workspace_id: str,
        proposed_by: str = "system",
        record_id: str | None = None,
        expected_version: int | None = None,
        trace_id: str | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """创建变更提案，自动计算 risk_level(low/high)"""
        # 验证对象类型
        defn = self._registry.get(object_type)
        if not defn:
            raise ObjectNotFoundError(f"对象类型不存在: {object_type}")

        op = OperationType(operation)

        # 验证字段（create/update 时）
        if op in (OperationType.CREATE, OperationType.UPDATE):
            errors = self._registry.validate_fields(object_type, changes)
            if errors:
                raise ValidationError(f"字段校验失败: {'; '.join(errors)}")

        # update/archive 时需要 record_id 和 expected_version
        diff_snapshot: dict[str, Any] | None = None
        if op in (OperationType.UPDATE, OperationType.ARCHIVE):
            if not record_id:
                raise InvalidProposalError(f"{op.value} 操作需要 record_id")
            if expected_version is None:
                raise InvalidProposalError(f"{op.value} 操作需要 expected_version")
            # 读取当前记录生成 diff
            current = await self._records.get_by_id(object_type, record_id)
            if current is None:
                raise RecordNotFoundError(f"记录不存在: {record_id}")
            if op == OperationType.UPDATE:
                before = {k: current.get(k) for k in changes}
                diff_snapshot = {"before": before, "after": changes}

        risk_level = _compute_risk_level(op, changes)
        proposal_id = str(uuid.uuid4())
        now = _now_iso()

        proposal = ChangeProposal(
            proposal_id=proposal_id,
            object_type=object_type,
            operation=op,
            record_id=record_id,
            changes=changes,
            summary=summary,
            diff_snapshot=diff_snapshot,
            risk_level=risk_level,
            status=ProposalStatus.PENDING,
            proposed_by=proposed_by,
            expected_version=expected_version,
            expires_at=expires_at,
            trace_id=trace_id,
            workspace_id=workspace_id,
            created_at=now,
        )

        # 持久化
        await self._workflow.insert_proposal(self._proposal_to_dict(proposal))

        return self._proposal_to_dict(proposal)


    async def commit_proposal(
        self,
        proposal_id: str,
        approved_by: str = "system",
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """
        执行已批准的提案。
        幂等保护：非 pending 返回确定性错误，同一 proposal 绝不重复生效。
        自动路由：schema 操作委托给 SchemaOps。
        """
        raw = await self._workflow.get_proposal(proposal_id)
        if raw is None:
            raise InvalidProposalError(f"提案不存在: {proposal_id}")

        # 路由 schema 操作
        op_str = raw.get("operation", "")
        if op_str in ("create_object", "alter_object", "drop_object"):
            from .schema_ops import SchemaOps
            schema_ops = SchemaOps(
                registry=self._registry,
                workflow_storage=self._workflow,
                schema_storage=self._schema_storage,
            )
            return await schema_ops.commit_schema_proposal(proposal_id, approved_by)

        status = raw["status"]
        if status == ProposalStatus.COMMITTED.value:
            raise InvalidProposalError(
                f"提案已提交，不可重复执行",
            )
        if status in (ProposalStatus.REJECTED.value, ProposalStatus.EXPIRED.value):
            raise InvalidProposalError(f"提案状态无效: {status}")
        if status != ProposalStatus.PENDING.value:
            raise InvalidProposalError(f"提案状态无效: {status}")

        # 检查过期
        if raw.get("expires_at"):
            expires = datetime.fromisoformat(raw["expires_at"])
            if datetime.now(timezone.utc) > expires:
                await self._workflow.update_proposal_status(
                    proposal_id, ProposalStatus.EXPIRED.value
                )
                raise InvalidProposalError("提案已过期")

        op = OperationType(raw["operation"])
        object_type = raw["object_type"]
        changes = raw["changes"]
        record_id = raw.get("record_id")
        expected_version = raw.get("expected_version")
        workspace_id = raw["workspace_id"]
        now = _now_iso()

        before_snapshot: dict[str, Any] | None = None
        after_snapshot: dict[str, Any] = {}
        result_record: dict[str, Any] = {}

        if op == OperationType.CREATE:
            new_id = str(uuid.uuid4())
            record = {
                "id": new_id,
                "workspace_id": workspace_id,
                "created_at": now,
                "updated_at": now,
                "created_by": approved_by,
                "version": 1,
                **changes,
            }
            result_record = await self._records.insert(object_type, record)
            after_snapshot = result_record
            record_id = new_id

        elif op == OperationType.UPDATE:
            if not record_id or expected_version is None:
                raise InvalidProposalError("update 操作缺少 record_id 或 expected_version")
            before_snapshot = await self._records.get_by_id(object_type, record_id)
            update_changes = {
                **changes,
                "updated_at": now,
                "version": expected_version + 1,
            }
            result_record = await self._records.update(
                object_type, record_id, update_changes, expected_version
            )
            after_snapshot = result_record

        elif op == OperationType.ARCHIVE:
            if not record_id or expected_version is None:
                raise InvalidProposalError("archive 操作缺少 record_id 或 expected_version")
            before_snapshot = await self._records.get_by_id(object_type, record_id)
            result_record = await self._records.archive(object_type, record_id, expected_version)
            after_snapshot = result_record

        # 写入审计日志
        audit = AuditLogEntry(
            change_id=str(uuid.uuid4()),
            object_type=object_type,
            record_id=record_id or "",
            operation=op,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            proposal_id=proposal_id,
            actor=approved_by,
            trace_id=trace_id or raw.get("trace_id"),
            changed_at=now,
        )
        await self._workflow.insert_audit_log(self._audit_to_dict(audit))

        # 更新提案状态
        await self._workflow.update_proposal_status(
            proposal_id,
            ProposalStatus.COMMITTED.value,
            approved_by=approved_by,
            approved_at=now,
        )

        return {
            "proposal_id": proposal_id,
            "status": "committed",
            "record": result_record,
            "record_id": record_id,
        }


    async def preview(
        self,
        object_type: str,
        operation: str,
        changes: dict[str, Any],
        record_id: str | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """只计算 diff/risk 不落库，与 propose 分离"""
        defn = self._registry.get(object_type)
        if not defn:
            raise ObjectNotFoundError(f"对象类型不存在: {object_type}")

        op = OperationType(operation)
        diff_snapshot: dict[str, Any] | None = None

        if op in (OperationType.UPDATE, OperationType.ARCHIVE) and record_id:
            current = await self._records.get_by_id(object_type, record_id)
            if current is None:
                raise RecordNotFoundError(f"记录不存在: {record_id}")
            if op == OperationType.UPDATE:
                before = {k: current.get(k) for k in changes}
                diff_snapshot = {"before": before, "after": changes}

        risk_level = _compute_risk_level(op, changes)

        return {
            "object_type": object_type,
            "operation": operation,
            "risk_level": risk_level,
            "diff_snapshot": diff_snapshot,
        }

    # ── 序列化辅助 ──

    @staticmethod
    def _proposal_to_dict(p: ChangeProposal) -> dict[str, Any]:
        return {
            "proposal_id": p.proposal_id,
            "object_type": p.object_type,
            "operation": p.operation.value if isinstance(p.operation, OperationType) else p.operation,
            "record_id": p.record_id,
            "changes": p.changes,
            "summary": p.summary,
            "diff_snapshot": p.diff_snapshot,
            "risk_level": p.risk_level,
            "status": p.status.value if isinstance(p.status, ProposalStatus) else p.status,
            "proposed_by": p.proposed_by,
            "expected_version": p.expected_version,
            "expires_at": p.expires_at,
            "trace_id": p.trace_id,
            "workspace_id": p.workspace_id,
            "created_at": p.created_at,
        }

    @staticmethod
    def _audit_to_dict(a: AuditLogEntry) -> dict[str, Any]:
        return {
            "change_id": a.change_id,
            "object_type": a.object_type,
            "record_id": a.record_id,
            "operation": a.operation.value if isinstance(a.operation, OperationType) else a.operation,
            "before_snapshot": a.before_snapshot,
            "after_snapshot": a.after_snapshot,
            "proposal_id": a.proposal_id,
            "actor": a.actor,
            "trace_id": a.trace_id,
            "reason": a.reason,
            "changed_at": a.changed_at,
        }
