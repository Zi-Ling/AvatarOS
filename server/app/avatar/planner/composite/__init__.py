"""
复合任务分析器模块

职责：
- 分析任务复杂度（要不要拆分？）
- 优化分解结果（去重、依赖检查、DAG构建）

注意：任务分解（TaskDecomposer）已移至 orchestrator/decomposer/
"""
from .analyzer import ComplexityAnalyzer, DecomposeDecision

__all__ = [
    "ComplexityAnalyzer",
    "DecomposeDecision",
]

