"""
审批历史记录器
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ApprovalHistory:
    """审批历史记录"""
    
    skill_name: str
    params: Dict
    risk_level: str
    user_decision: str  # "approved" | "rejected"
    timestamp: datetime
    user_id: Optional[str] = None


class ApprovalHistoryRecorder:
    """
    审批历史记录器
    
    职责：
    - 记录用户的审批决策
    - 分析审批模式
    - 生成自动批准规则
    """
    
    def __init__(self):
        self._history: List[ApprovalHistory] = []
    
    def record(
        self,
        skill_name: str,
        params: Dict,
        risk_level: str,
        user_decision: str,
        user_id: Optional[str] = None
    ):
        """
        记录审批决策
        
        Args:
            skill_name: 技能名称
            params: 参数
            risk_level: 风险等级
            user_decision: 用户决策
            user_id: 用户ID（可选）
        """
        record = ApprovalHistory(
            skill_name=skill_name,
            params=params,
            risk_level=risk_level,
            user_decision=user_decision,
            timestamp=datetime.now(),
            user_id=user_id
        )
        
        self._history.append(record)
        logger.info(
            f"Recorded approval: {skill_name} -> {user_decision}"
        )
    
    def get_approval_rate(
        self,
        skill_name: str,
        user_id: Optional[str] = None
    ) -> float:
        """
        获取某个技能的批准率
        
        Args:
            skill_name: 技能名称
            user_id: 用户ID（可选，None 表示所有用户）
        
        Returns:
            float: 批准率（0.0-1.0）
        """
        records = [
            r for r in self._history
            if r.skill_name == skill_name and (user_id is None or r.user_id == user_id)
        ]
        
        if not records:
            return 0.5  # 默认50%
        
        approved_count = sum(1 for r in records if r.user_decision == "approved")
        return approved_count / len(records)
    
    def should_auto_approve(
        self,
        skill_name: str,
        threshold: float = 0.9,
        min_samples: int = 5,
        user_id: Optional[str] = None
    ) -> bool:
        """
        基于历史判断是否应该自动批准
        
        Args:
            skill_name: 技能名称
            threshold: 批准率阈值（默认90%）
            min_samples: 最小样本数（默认5次）
            user_id: 用户ID（可选）
        
        Returns:
            bool: True 表示应该自动批准
        """
        records = [
            r for r in self._history
            if r.skill_name == skill_name and (user_id is None or r.user_id == user_id)
        ]
        
        if len(records) < min_samples:
            return False  # 样本不足
        
        approval_rate = self.get_approval_rate(skill_name, user_id)
        
        if approval_rate >= threshold:
            logger.info(
                f"Auto-approve rule: {skill_name} "
                f"(rate={approval_rate:.2f}, samples={len(records)})"
            )
            return True
        
        return False
    
    def get_recent_history(
        self,
        limit: int = 10,
        user_id: Optional[str] = None
    ) -> List[ApprovalHistory]:
        """
        获取最近的审批历史
        
        Args:
            limit: 返回数量限制
            user_id: 用户ID（可选）
        
        Returns:
            List[ApprovalHistory]: 历史记录列表
        """
        records = [
            r for r in self._history
            if user_id is None or r.user_id == user_id
        ]
        
        # 按时间倒序排序
        records.sort(key=lambda r: r.timestamp, reverse=True)
        
        return records[:limit]

