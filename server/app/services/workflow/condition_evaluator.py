# server/app/services/workflow/condition_evaluator.py
"""
条件表达式求值，纯内存计算。

正确性属性 P8 依赖此模块正确求值条件。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .models import ConditionExpr

logger = logging.getLogger(__name__)


class ConditionEvaluator:
    """条件表达式求值"""

    def evaluate(
        self,
        condition: Optional[ConditionExpr],
        step_outputs: dict[str, dict[str, Any]],
    ) -> bool:
        """
        求值条件表达式链。

        step_outputs 格式: {"step_id": {"output_key": value, ...}, ...}
        condition 为 None → True（无条件，始终执行）
        """
        if condition is None:
            return True
        return self._eval_chain(condition, step_outputs)

    def _eval_chain(
        self, expr: ConditionExpr, step_outputs: dict[str, dict[str, Any]]
    ) -> bool:
        """递归求值条件链。"""
        current_result = self._eval_single(expr, step_outputs)

        if expr.logic is None or expr.next is None:
            return current_result

        next_result = self._eval_chain(expr.next, step_outputs)

        if expr.logic == "and":
            return current_result and next_result
        else:  # "or"
            return current_result or next_result

    def _eval_single(
        self, expr: ConditionExpr, step_outputs: dict[str, dict[str, Any]]
    ) -> bool:
        """求值单个条件表达式。"""
        left_value = self._resolve_ref(expr.left, step_outputs)
        return self._compare(left_value, expr.operator, expr.right)

    def _resolve_ref(
        self, ref: str, step_outputs: dict[str, dict[str, Any]]
    ) -> Any:
        """
        解析 steps.<step_id>.outputs.<key> 引用路径。

        返回 None 如果路径不存在。
        """
        parts = ref.split(".")
        # 期望格式: steps.<step_id>.outputs.<key>
        if len(parts) != 4 or parts[0] != "steps" or parts[2] != "outputs":
            logger.warning(f"无效的引用路径格式: {ref}")
            return None

        step_id = parts[1]
        output_key = parts[3]

        step_out = step_outputs.get(step_id)
        if step_out is None:
            return None
        return step_out.get(output_key)

    @staticmethod
    def _compare(left: Any, operator: str, right: Any) -> bool:
        """
        执行单个比较操作。

        None 与任何值比较返回 False。
        类型不匹配时尝试数值转换，转换失败返回 False。
        """
        # None 安全处理：None == None → True, None != None → False
        if left is None and right is None:
            return operator in ("==", ">=", "<=")
        if left is None or right is None:
            return operator == "!="

        # 尝试数值转换以支持跨类型比较
        cmp_left, cmp_right = left, right
        if type(left) != type(right):
            try:
                cmp_left = float(left)
                cmp_right = float(right)
            except (ValueError, TypeError):
                # 非数值比较，保持原始类型
                cmp_left, cmp_right = left, right

        try:
            if operator == "==":
                return cmp_left == cmp_right
            elif operator == "!=":
                return cmp_left != cmp_right
            elif operator == ">":
                return cmp_left > cmp_right
            elif operator == "<":
                return cmp_left < cmp_right
            elif operator == ">=":
                return cmp_left >= cmp_right
            elif operator == "<=":
                return cmp_left <= cmp_right
        except TypeError:
            return False
        return False
