# server/app/avatar/skills/core/approval.py

from __future__ import annotations

import logging
from typing import Optional, Any, Dict
from pydantic import Field

from ..base import BaseSkill, SkillSpec, SkillCategory, SkillPermission, SkillMetadata, SkillDomain, SkillCapability, SkillRiskLevel
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext
from app.services.approval_service import get_approval_service

logger = logging.getLogger(__name__)


# ============================================================================
# approval.request - 请求人工审批
# ============================================================================

class ApprovalRequestInput(SkillInput):
    message: str = Field(..., description="Approval message to show to user")
    operation: str = Field(..., description="Operation type (e.g., 'delete_file', 'send_email')")
    details: Optional[Dict[str, Any]] = Field(None, description="Operation details")
    timeout_seconds: int = Field(60, description="Timeout in seconds (default 60)")

class ApprovalRequestOutput(SkillOutput):
    output: Optional[bool] = Field(None, description="Primary output: approval result")
    request_id: str
    approved: bool = False
    timeout: bool = False

@register_skill
class ApprovalRequestSkill(BaseSkill[ApprovalRequestInput, ApprovalRequestOutput]):
    spec = SkillSpec(
        name="approval.request",
        api_name="approval.request",
        aliases=["request_approval", "ask_permission"],
        description="Request human approval for sensitive operations. 请求人工审批敏感操作。",
        category=SkillCategory.SYSTEM,
        input_model=ApprovalRequestInput,
        output_model=ApprovalRequestOutput,
        
        meta=SkillMetadata(
            domain=SkillDomain.SYSTEM,
            capabilities={SkillCapability.WRITE},
            risk_level=SkillRiskLevel.SAFE,
            priority=10,
        ),
        
        synonyms=["ask permission", "request confirmation", "请求审批", "请求确认"],
        
        examples=[
            {"description": "Request file deletion", "params": {"message": "Delete important file?", "operation": "delete_file", "details": {"path": "/important/file.txt"}}},
            {"description": "Request email send", "params": {"message": "Send email to all users?", "operation": "send_email", "details": {"recipients": 100}}},
        ],
        
        permissions=[SkillPermission(name="approval_request", description="Request approval")],
        tags=["approval", "permission", "审批", "权限"]
    )

    async def run(self, ctx: SkillContext, params: ApprovalRequestInput) -> ApprovalRequestOutput:
        if ctx.dry_run:
            return ApprovalRequestOutput(
                success=True,
                message=f"[dry_run] Would request approval: {params.message}",
                request_id="dry_run_id",
                approved=True,
                timeout=False,
                output=True
            )

        try:
            # 生成幂等的 request_id
            task_id = ctx.execution_context.task_id if ctx.execution_context else "unknown"
            step_id = ctx.execution_context.step_id if ctx.execution_context else "unknown"
            request_id = f"approval_{task_id}_{step_id}"
            
            service = get_approval_service()
            
            # 创建审批请求（幂等）
            request = service.create_request(
                request_id=request_id,
                message=params.message,
                operation=params.operation,
                task_id=task_id,
                step_id=step_id,
                details=params.details,
                timeout_seconds=params.timeout_seconds
            )
            
            # 如果已经有结果（幂等性），直接返回
            if request['status'] in ('approved', 'denied', 'timeout', 'expired'):
                approved = request['status'] == 'approved'
                timeout = request['status'] in ('timeout', 'expired')
                
                return ApprovalRequestOutput(
                    success=True,
                    message=f"Approval request already responded: {request['status']}",
                    request_id=request_id,
                    approved=approved,
                    timeout=timeout,
                    output=approved
                )
            
            # 等待审批结果
            try:
                approved = await service.wait_for_approval(
                    request_id=request_id,
                    timeout_seconds=params.timeout_seconds
                )
                
                return ApprovalRequestOutput(
                    success=True,
                    message=f"Approval {'granted' if approved else 'denied'}",
                    request_id=request_id,
                    approved=approved,
                    timeout=False,
                    output=approved
                )
            
            except TimeoutError:
                return ApprovalRequestOutput(
                    success=False,
                    message="Approval request timeout",
                    request_id=request_id,
                    approved=False,
                    timeout=True,
                    output=False
                )
        
        except Exception as e:
            return ApprovalRequestOutput(
                success=False,
                message=str(e),
                request_id="",
                approved=False,
                timeout=False,
                output=False
            )
