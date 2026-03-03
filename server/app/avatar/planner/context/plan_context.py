from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class PlanContext:
    """
    LLM / 规则 生成计划阶段的上下文。
    用于给 planner 提供更多信号，同时存储中间产物（例如多轮提示）。
    """

    user_goal: str                      # 用户的自然语言目标
    raw_input: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # LLM 相关
    llm_prompt: Optional[str] = None
    llm_raw_response: Optional[str] = None

    # 调试 / 追踪
    trace: Dict[str, Any] = field(default_factory=dict)

    def add_trace(self, key: str, value: Any) -> None:
        self.trace[key] = value
