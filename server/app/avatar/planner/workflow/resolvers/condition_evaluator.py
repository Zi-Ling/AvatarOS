"""
Condition Evaluator

Safely evaluates condition expressions for workflow stages.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from ..models import WorkflowRun, StageRunStatus

logger = logging.getLogger(__name__)


class ConditionEvaluator:
    """
    条件评估器
    
    安全地评估条件表达式
    
    TODO: 替代当前的 eval() 实现，使用沙箱化的表达式解析器
    参考: jinja2.sandbox 或 simpleeval 库
    """
    
    @staticmethod
    def evaluate(condition: str, run: WorkflowRun) -> bool:
        """
        评估条件表达式
        
        Args:
            condition: 条件表达式
            run: WorkflowRun 对象
            
        Returns:
            条件是否满足
        """
        try:
            # 构建上下文
            context = {
                "inputs": run.inputs,
                "context": run.context
            }
            
            # 添加阶段输出
            for stage_run in run.stage_runs:
                if stage_run.status == StageRunStatus.SUCCESS:
                    context[stage_run.stage_id] = stage_run.outputs
            
            # 评估表达式（TODO: 使用安全的评估器）
            result = eval(condition, {"__builtins__": {}}, context)
            return bool(result)
            
        except Exception as e:
            logger.warning(f"Failed to evaluate condition '{condition}': {e}")
            return False
    
    @staticmethod
    def evaluate_safe(condition: str, run: WorkflowRun) -> bool:
        """
        安全评估（未来实现）
        
        使用沙箱化的表达式引擎：
        - 支持常见操作符 (==, >, <, and, or)
        - 支持自定义函数 (has_artifact(), user_confirmed())
        - 禁止危险操作
        """
        # TODO: 实现安全的评估器
        return ConditionEvaluator.evaluate(condition, run)

