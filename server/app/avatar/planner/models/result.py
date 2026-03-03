from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

from .plan import Plan


@dataclass
class PlanResult:
    """
    Planner 规划完成后的结果包装。
    """
    plan: Plan
    # 可以附带一些元数据（LLM token 花费等）
    metadata: Dict[str, Any] = field(default_factory=dict)
