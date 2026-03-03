"""
审批管理器
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, TYPE_CHECKING

from .risk import RiskAnalyzer, RiskLevel
from .policies import ApprovalPolicy, RiskBasedPolicy
from .history import ApprovalHistoryRecorder

if TYPE_CHECKING:
    from ..runtime.events import EventBus

logger = logging.getLogger(__name__)


@dataclass
class ApprovalRequest:
    """审批请求"""
    
    subtask_id: str
    skill_name: str
    params: Dict[str, Any]
    risk_level: RiskLevel
    warnings: list
    goal: str


@dataclass
class ApprovalResponse:
    """审批响应"""
    
    approved: bool
    reason: Optional[str] = None
    modified_params: Optional[Dict] = None


class ApprovalManager:
    """
    审批管理器
    
    职责：
    - 综合风险分析
    - 策略判断
    - 等待用户响应
    - 记录审批历史
    """
    
    def __init__(
        self,
        policy: Optional[ApprovalPolicy] = None,
        event_bus: Optional[Any] = None,
        timeout: int = 30
    ):
        """
        Args:
            policy: 审批策略（默认基于风险）
            event_bus: 事件总线（可选）
            timeout: 超时时间（秒，默认30s）
        """
        self._analyzer = RiskAnalyzer()
        self._policy = policy or RiskBasedPolicy()
        self._event_bus = event_bus
        self._timeout = timeout
        self._history = ApprovalHistoryRecorder()
        
        # 等待响应的 Future
        self._pending_approvals: Dict[str, asyncio.Future] = {}
    
    async def request_approval(
        self,
        subtask_id: str,
        skill_name: str,
        params: Dict[str, Any],
        goal: str,
        context: Optional[Dict] = None
    ) -> bool:
        """
        请求审批
        
        Args:
            subtask_id: 子任务ID
            skill_name: 技能名称
            params: 参数
            goal: 任务目标
            context: 上下文（可选）
        
        Returns:
            bool: True 表示批准，False 表示拒绝
        """
        # 1. 风险分析
        risk_level, warnings = self._analyzer.analyze(
            skill_name,
            params,
            context
        )
        
        logger.info(
            f"Approval request: {skill_name} (risk={risk_level}, warnings={len(warnings)})"
        )
        
        # 2. 检查历史，是否可以自动批准
        if self._history.should_auto_approve(skill_name):
            logger.info(f"Auto-approved based on history: {skill_name}")
            self._history.record(skill_name, params, risk_level.value, "approved")
            return True
        
        # 3. 策略判断
        if self._policy.should_approve_auto(skill_name, params, risk_level, context or {}):
            logger.info(f"Auto-approved by policy: {skill_name}")
            self._history.record(skill_name, params, risk_level.value, "approved")
            return True
        
        # 4. 需要用户确认
        logger.info(f"User approval required for: {skill_name}")
        
        # 创建审批请求
        request = ApprovalRequest(
            subtask_id=subtask_id,
            skill_name=skill_name,
            params=params,
            risk_level=risk_level,
            warnings=warnings,
            goal=goal
        )
        
        # 发送事件
        if self._event_bus:
            self._publish_approval_required(request, context)
        
        # 等待响应
        approved = await self._wait_for_response(subtask_id)
        
        # 记录历史
        decision = "approved" if approved else "rejected"
        self._history.record(skill_name, params, risk_level.value, decision)
        
        return approved
    
    async def _wait_for_response(self, subtask_id: str) -> bool:
        """
        等待用户响应
        
        Args:
            subtask_id: 子任务ID
        
        Returns:
            bool: True 表示批准
        """
        # 创建 Future
        future = asyncio.Future()
        self._pending_approvals[subtask_id] = future
        
        try:
            # 等待响应（带超时）
            approved = await asyncio.wait_for(future, timeout=self._timeout)
            return approved
        except asyncio.TimeoutError:
            logger.warning(f"Approval timeout for {subtask_id}, auto-rejecting")
            return False  # 超时默认拒绝
        finally:
            # 清理
            self._pending_approvals.pop(subtask_id, None)
    
    def submit_response(
        self,
        subtask_id: str,
        approved: bool,
        reason: Optional[str] = None
    ):
        """
        提交用户响应
        
        Args:
            subtask_id: 子任务ID
            approved: 是否批准
            reason: 原因（可选）
        """
        future = self._pending_approvals.get(subtask_id)
        
        if future and not future.done():
            future.set_result(approved)
            logger.info(
                f"Approval response received: {subtask_id} -> "
                f"{'approved' if approved else 'rejected'}"
            )
        else:
            logger.warning(f"No pending approval for {subtask_id}")
    
    def _publish_approval_required(
        self,
        request: ApprovalRequest,
        context: Optional[Dict]
    ):
        """发送审批请求事件"""
        try:
            from ...runtime.events import Event, EventType
            
            self._event_bus.publish(Event(
                type=EventType.APPROVAL_REQUIRED,
                source="approval_manager",
                payload={
                    "subtask_id": request.subtask_id,
                    "skill_name": request.skill_name,
                    "params": request.params,
                    "risk_level": request.risk_level.value,
                    "warnings": request.warnings,
                    "goal": request.goal,
                    "session_id": context.get("session_id") if context else None
                }
            ))
        except Exception as e:
            logger.warning(f"Failed to publish APPROVAL_REQUIRED event: {e}")

