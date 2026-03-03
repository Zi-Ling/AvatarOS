"""
审批策略抽象基类
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict
from ..risk import RiskLevel


class ApprovalPolicy(ABC):
    """
    审批策略抽象基类
    
    决定是否需要用户批准
    """
    
    @abstractmethod
    def should_approve_auto(
        self,
        skill_name: str,
        params: Dict[str, Any],
        risk_level: RiskLevel,
        context: Dict[str, Any]
    ) -> bool:
        """
        判断是否自动批准（不需要用户确认）
        
        Args:
            skill_name: 技能名称
            params: 参数
            risk_level: 风险等级
            context: 上下文
        
        Returns:
            bool: True 表示自动批准，False 表示需要用户确认
        """
        raise NotImplementedError

