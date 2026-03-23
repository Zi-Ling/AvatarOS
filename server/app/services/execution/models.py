"""执行路由层数据模型：ExecutionRequest、ExecutionResult、RoutingDecision 等。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel

from app.services.adapter.models import ExecutionLayer, RiskLevel, TargetType


class ExecutionRequest(BaseModel):
    """Strategy Router 接收的执行请求"""
    request_id: str
    target_description: str
    target_type: TargetType = TargetType.UNKNOWN
    risk_level: RiskLevel = RiskLevel.LOW
    requires_persistence: bool = False
    allows_degradation: bool = True
    allows_side_effects: bool = True
    constraints: dict[str, Any] = {}
    required_layer: Optional[ExecutionLayer] = None
    preferred_layer: Optional[ExecutionLayer] = None
    timeout_seconds: int = 300
    params: dict[str, Any] = {}


class RoutingDecision(BaseModel):
    """路由决策记录"""
    request_id: str
    selected_layer: ExecutionLayer
    reason: str
    alternatives: list[ExecutionLayer] = []
    timestamp: datetime


class DegradationEvent(BaseModel):
    """降级事件记录"""
    source_layer: ExecutionLayer
    target_layer: ExecutionLayer
    error_code: str
    failure_reason: str = ""
    failure_context_json: str
    timestamp: datetime


class ExecutionAttempt(BaseModel):
    """单次执行层尝试的完整轨迹"""
    layer: ExecutionLayer
    start_time: datetime
    end_time: Optional[datetime] = None
    success: bool = False
    result_summary: str = ""
    failure_context_json: Optional[str] = None
    duration_ms: float = 0.0


class ExecutionResult(BaseModel):
    """Strategy Router 统一执行结果"""
    success: bool
    final_layer: ExecutionLayer
    outputs: dict[str, Any] = {}
    attempts: list[ExecutionAttempt] = []
    degradation_events: list[DegradationEvent] = []
    routing_decision: RoutingDecision
    total_duration_ms: float = 0.0
    error_message: Optional[str] = None
