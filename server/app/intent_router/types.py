# router/types.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Any, Dict, Literal

from app.avatar.intent import IntentSpec


# ============ 新版路由决策（推荐使用） ============

@dataclass
class RouteDecision:
    """
    统一的路由决策结果
    
    用于 AvatarRouter.route() 返回，包含完整的意图判断和执行能力信息
    """
    intent_kind: Literal["chat", "task"]
    """意图类型：chat（普通对话）或 task（任务执行）"""
    
    task_mode: Literal["none", "one_shot", "recurring"] = "none"
    """任务模式：none（非任务）、one_shot（一次性）、recurring（定时重复）"""
    
    can_execute: bool = False
    """是否可以执行：True=有对应技能，False=理解意图但无技能"""
    
    intent_spec: Optional[IntentSpec] = None
    """任务规格（Deprecated: Router 不再生成详细 IntentSpec，由 Runtime 生成）"""
    
    goal: str = ""
    """任务目标简述（V2 新增）"""
    
    llm_explanation: str = ""
    """LLM 的自然语言解释"""
    
    missing_skills: list[str] = field(default_factory=list)
    """缺失的技能列表（仅当 can_execute=False 时）"""
    
    relevance_score: float = 0.0
    """技能相关性分数（0-1，越高越相关）"""
    
    top_skills: list[str] = field(default_factory=list)
    """最相关的技能列表（top-3）"""
    
    raw_llm_output: str = ""
    """原始 LLM 输出（调试用）"""

    think_process: str = ""
    """思考过程（CoT），通常在 <think> 标签内"""
    
    route_reason: str = ""
    """路由原因（方案A+B新增）：complex_task_force_planner, high_confidence, low_confidence_planner, too_low_score等"""
    
    is_complex: bool = False
    """复杂度判断结果（Router 层统一判断，传递给下游避免重复计算）"""
    
    scored_skills: list[dict] = field(default_factory=list)
    """Router 层的技能搜索结果（带分数），传递给 Planner 避免重复向量搜索
    格式: [{"name": "web.open", "score": 0.85}, ...]"""


# ============ 旧版路由结果（向后兼容） ============

class RouterResult:
    """基类：所有 Router 返回类型均继承于此"""
    type: str


@dataclass
class ChatResult(RouterResult):
    type: str = "chat"
    text: str = ""


@dataclass
class IntentResult(RouterResult):
    type: str = "intent"
    intent: IntentSpec | None = None


@dataclass
class ErrorResult(RouterResult):
    type: str = "error"
    error: str = ""
    raw_output: str = ""
