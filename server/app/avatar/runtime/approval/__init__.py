"""
审批模块 - 危险操作确认

职责：
- 风险分析（技能 + 参数 + 上下文）
- 审批策略判断（要不要问用户？）
- 等待用户响应（超时处理）
- 审批历史记录
"""
from .manager import ApprovalManager, ApprovalRequest, ApprovalResponse
from .risk import RiskAnalyzer, RiskLevel
from .policies import ApprovalPolicy, RiskBasedPolicy, UserModePolicy

__all__ = [
    "ApprovalManager",
    "ApprovalRequest",
    "ApprovalResponse",
    "RiskAnalyzer",
    "RiskLevel",
    "ApprovalPolicy",
    "RiskBasedPolicy",
    "UserModePolicy",
]

