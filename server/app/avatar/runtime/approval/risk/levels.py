"""
风险等级定义
"""
from __future__ import annotations

from enum import Enum


class RiskLevel(str, Enum):
    """
    风险等级枚举
    
    级别说明：
    - LOW: 只读操作，无副作用
    - MEDIUM: 可逆修改，可以撤销
    - HIGH: 不可逆操作，难以恢复
    - CRITICAL: 系统级操作，可能造成严重后果
    """
    
    LOW = "low"           # 只读操作（file.read, web.get）
    MEDIUM = "medium"     # 可逆修改（file.write, 创建资源）
    HIGH = "high"         # 不可逆操作（delete, execute）
    CRITICAL = "critical" # 系统级操作（sudo, 数据库drop）
    
    @property
    def score(self) -> int:
        """风险分数（用于比较）"""
        scores = {
            RiskLevel.LOW: 1,
            RiskLevel.MEDIUM: 2,
            RiskLevel.HIGH: 3,
            RiskLevel.CRITICAL: 4
        }
        return scores[self]
    
    def __gt__(self, other: RiskLevel) -> bool:
        """支持比较操作"""
        return self.score > other.score
    
    def __ge__(self, other: RiskLevel) -> bool:
        return self.score >= other.score
    
    def __lt__(self, other: RiskLevel) -> bool:
        return self.score < other.score
    
    def __le__(self, other: RiskLevel) -> bool:
        return self.score <= other.score

