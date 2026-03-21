# server/app/avatar/skills/core/approval.py

from __future__ import annotations

import logging
from typing import Optional, Any, Dict
from pydantic import Field

from ..base import BaseSkill, SkillSpec, SideEffect, SkillRiskLevel
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext
from app.avatar.runtime.graph.models.output_contract import SkillOutputContract, ValueKind, TransportMode
from app.services.approval_service import get_approval_service

logger = logging.getLogger(__name__)


class ApprovalRequestInput(SkillInput):
    message: str = Field(..., description="Approval message to show to user")
    operation: str = Field(..., description="Operation type (e.g., 'delete_file')")
    details: Optional[Dict[str, Any]] = Field(None, description="Operation details")
    timeout_seconds: int = Field(60, description="Timeout in seconds")

class ApprovalRequestOutput(SkillOutput):
    output: Optional[bool] = Field(None, description="Approval result")
    request_id: str
    approved: bool = False
    timeout: bool = False

@register_skill
class ApprovalRequestSkill(BaseSkill[ApprovalRequestInput, ApprovalRequestOutput]):
    spec = SkillSpec(
        name="approval.request",
        description="Request human approval for sensitive operations. 请求人工审批。",
        input_model=ApprovalRequestInput,
        output_model=ApprovalRequestOutput,
        side_effects={SideEffect.HUMAN},
        risk_level=SkillRiskLevel.SYSTEM,
        aliases=["request_approval", "ask_permission"],
        tags=["approve", "permission", "审批", "授权"],
        output_contract=SkillOutputContract(value_kind=ValueKind.JSON, transport_mode=TransportMode.INLINE),
    )

    async def run(self, ctx: SkillContext, params: ApprovalRequestInput) -> ApprovalRequestOutput:
        if ctx.dry_run:
            return ApprovalRequestOutput(success=True, message="[dry_run] Would request approval",
                                         request_id="dry_run_id", approved=True, output=True)

        try:
            task_id = ctx.execution_context.task_id if ctx.execution_context else "unknown"
            step_id = ctx.execution_context.step_id if ctx.execution_context else "unknown"
            request_id = f"approval_{task_id}_{step_id}"

            service = get_approval_service()
            request = service.create_request(
                request_id=request_id,
                message=params.message,
                operation=params.operation,
                task_id=task_id,
                step_id=step_id,
                details=params.details,
                timeout_seconds=params.timeout_seconds,
            )

            if request["status"] in ("approved", "denied", "timeout", "expired"):
                approved = request["status"] == "approved"
                timeout = request["status"] in ("timeout", "expired")
                return ApprovalRequestOutput(success=True, message=f"Already responded: {request['status']}",
                                             request_id=request_id, approved=approved, timeout=timeout, output=approved)

            try:
                approved = await service.wait_for_approval(request_id=request_id, timeout_seconds=params.timeout_seconds)
                return ApprovalRequestOutput(success=True, message=f"Approval {'granted' if approved else 'denied'}",
                                             request_id=request_id, approved=approved, output=approved)
            except TimeoutError:
                return ApprovalRequestOutput(success=False, message="Approval request timeout",
                                             request_id=request_id, approved=False, timeout=True, output=False)
        except Exception as e:
            return ApprovalRequestOutput(success=False, message=str(e), request_id="", approved=False, output=False)
