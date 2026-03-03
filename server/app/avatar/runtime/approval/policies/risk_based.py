"""
基于风险等级的审批策略
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from .base import ApprovalPolicy
from ..risk import RiskLevel

logger = logging.getLogger(__name__)


class RiskBasedPolicy(ApprovalPolicy):
    """
    基于风险等级的审批策略
    
    规则：
    - LOW: 自动批准
    - MEDIUM: 自动批准（可配置）
    - HIGH: 需要确认
    - CRITICAL: 需要确认 + 二次验证
    """
    
    def __init__(
        self,
        auto_approve_low: bool = True,
        auto_approve_medium: bool = True,
        auto_approve_high: bool = False
    ):
        """
        Args:
            auto_approve_low: 自动批准 LOW 风险
            auto_approve_medium: 自动批准 MEDIUM 风险
            auto_approve_high: 自动批准 HIGH 风险
        """
        self._auto_approve_low = auto_approve_low
        self._auto_approve_medium = auto_approve_medium
        self._auto_approve_high = auto_approve_high
    
    def should_approve_auto(
        self,
        skill_name: str,
        params: Dict[str, Any],
        risk_level: RiskLevel,
        context: Dict[str, Any]
    ) -> bool:
        """判断是否自动批准"""
        if risk_level == RiskLevel.LOW:
            return self._auto_approve_low
        
        if risk_level == RiskLevel.MEDIUM:
            return self._auto_approve_medium
        
        if risk_level == RiskLevel.HIGH:
            return self._auto_approve_high
        
        if risk_level == RiskLevel.CRITICAL:
            # CRITICAL 永远不自动批准
            logger.warning(f"CRITICAL operation requires manual approval: {skill_name}")
            return False
        
        # 默认需要确认
        return False

