"""
基于用户模式的审批策略
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict

from .base import ApprovalPolicy
from ..risk import RiskLevel

logger = logging.getLogger(__name__)


class UserMode(str, Enum):
    """用户模式枚举"""
    
    SHADOW = "shadow"        # 影子模式：自动批准所有操作，但记录
    ACTIVE = "active"        # 主动模式：危险操作需要确认
    LEARNING = "learning"    # 学习模式：显示确认框但默认批准
    EXPERT = "expert"        # 专家模式：只有 CRITICAL 需要确认


class UserModePolicy(ApprovalPolicy):
    """
    基于用户模式的审批策略
    
    不同模式有不同的确认要求
    """
    
    def __init__(self, mode: UserMode = UserMode.ACTIVE):
        """
        Args:
            mode: 用户模式
        """
        self._mode = mode
    
    def set_mode(self, mode: UserMode):
        """设置用户模式"""
        self._mode = mode
        logger.info(f"User mode set to: {mode}")
    
    def should_approve_auto(
        self,
        skill_name: str,
        params: Dict[str, Any],
        risk_level: RiskLevel,
        context: Dict[str, Any]
    ) -> bool:
        """根据用户模式判断是否自动批准"""
        if self._mode == UserMode.SHADOW:
            # Shadow 模式：自动批准所有，但记录
            logger.info(
                f"[Shadow] Auto-approved: {skill_name} (risk={risk_level})"
            )
            return True
        
        if self._mode == UserMode.LEARNING:
            # Learning 模式：显示但默认批准（实际在 UI 层处理）
            # 这里返回 False 触发审批流程，但 UI 会自动倒计时批准
            return False
        
        if self._mode == UserMode.EXPERT:
            # Expert 模式：只有 CRITICAL 需要确认
            if risk_level >= RiskLevel.CRITICAL:
                return False
            return True
        
        # Active 模式（默认）：HIGH 及以上需要确认
        if self._mode == UserMode.ACTIVE:
            if risk_level >= RiskLevel.HIGH:
                return False
            return True
        
        # 默认需要确认
        return False

