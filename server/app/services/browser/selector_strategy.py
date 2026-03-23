# server/app/services/browser/selector_strategy.py
"""DOM 选择器策略：优先级排序与质量评分。"""
from __future__ import annotations

from app.services.browser.models import (
    BrowserErrorCode,
    SELECTOR_PRIORITY,
    SelectorCandidate,
    SelectorResolution,
    SelectorType,
)


# 类型权重基础分（满分 100）
_TYPE_BASE_SCORE: dict[SelectorType, int] = {
    SelectorType.ROLE: 90,
    SelectorType.LABEL: 90,
    SelectorType.DATA_TESTID: 80,
    SelectorType.CSS: 60,
    SelectorType.TEXT: 40,
    SelectorType.XPATH: 20,
}


class SelectorStrategy:
    """选择器优先级与质量评分。"""

    def score(self, selector: SelectorCandidate) -> int:
        """计算选择器质量评分 (0-100)。"""
        base = _TYPE_BASE_SCORE.get(selector.selector_type, 30)
        # 短表达式更稳定
        length_penalty = min(len(selector.expression) // 20, 20)
        # 含 id 或 data-testid 加分
        bonus = 0
        expr_lower = selector.expression.lower()
        if "id=" in expr_lower or "#" in expr_lower:
            bonus = 10
        return max(0, min(100, base - length_penalty + bonus))

    def resolve(
        self,
        candidates: list[SelectorCandidate],
        match_fn: callable | None = None,
    ) -> SelectorResolution:
        """
        按优先级排序候选选择器，返回解析结果。

        match_fn: 可选回调 (expression: str) -> int，返回匹配元素数量。
                  测试中可传入 mock。未提供时假设每个选择器匹配 1 个元素。
        """
        if not candidates:
            raise ValueError("No selector candidates provided")

        # 按优先级排序（数值越小越优先，相同优先级保持原序）
        sorted_candidates = sorted(
            candidates,
            key=lambda c: SELECTOR_PRIORITY.get(c.selector_type, 99),
        )

        for candidate in sorted_candidates:
            if match_fn is not None:
                count = match_fn(candidate.expression)
            else:
                count = 1  # 默认假设匹配

            if count > 0:
                return SelectorResolution(
                    adopted=candidate,
                    match_count=count,
                    quality_score=self.score(candidate),
                    all_candidates=list(candidates),
                )

        # 所有候选都未匹配
        raise LookupError(
            f"No selector matched. Tried: "
            f"{[c.expression for c in sorted_candidates]}"
        )
