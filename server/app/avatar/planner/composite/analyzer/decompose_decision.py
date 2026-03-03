"""
分解决策数据类
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class DecomposeDecision:
    """
    分解决策结果
    
    Attributes:
        should_decompose: 是否应该分解
        reason: 决策原因
        confidence: 置信度（0.0-1.0）
        method: 决策方法（"semantic", "keyword", "intent"）
    """
    
    should_decompose: bool
    reason: str
    confidence: float = 1.0
    method: Optional[str] = None

