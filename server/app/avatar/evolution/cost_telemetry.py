"""
cost_telemetry.py — CostTelemetryAggregator

从 BudgetAccount 的 CostRecord 流中聚合演化分析所需的成本遥测。
支持按 step 级别的成本明细和副作用记录。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.avatar.evolution.models import (
    CostTelemetry,
    SideEffectType,
    StepCostEntry,
)

logger = logging.getLogger(__name__)


class CostTelemetryAggregator:
    """
    从 BudgetAccount 聚合演化分析所需的成本遥测。
    BudgetAccount 关注预算控制，CostTelemetry 关注演化分析，两者共享数据源但维护独立分析视图。
    """

    def __init__(self, budget_account: Any = None) -> None:
        self._budget_account = budget_account
        # 临时存储：trace_id -> side_effects
        self._side_effects: Dict[str, Dict[SideEffectType, int]] = {}
        # 临时存储：trace_id -> step_costs
        self._step_costs: Dict[str, List[StepCostEntry]] = {}

    def record_step_cost(
        self,
        trace_id: str,
        step_id: str,
        tokens: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        duration_ms: int = 0,
        model_name: str = "",
    ) -> None:
        """记录单步成本。"""
        entry = StepCostEntry(
            step_id=step_id,
            tokens=tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_ms=duration_ms,
            model_name=model_name,
        )
        self._step_costs.setdefault(trace_id, []).append(entry)

    def record_side_effect(
        self,
        trace_id: str,
        step_id: str,
        effect_type: SideEffectType,
    ) -> None:
        """记录副作用事件，按类型累计。"""
        effects = self._side_effects.setdefault(trace_id, {})
        effects[effect_type] = effects.get(effect_type, 0) + 1

    def aggregate_for_trace(
        self,
        trace_id: str,
        task_id: str,
        session_id: str,
        start_time: float,
        end_time: float,
    ) -> CostTelemetry:
        """从已记录的步骤成本和 BudgetAccount 聚合任务级成本遥测。"""
        step_costs = self._step_costs.get(trace_id, [])
        side_effects = self._side_effects.get(trace_id, {})

        total_tokens = sum(e.tokens for e in step_costs)
        prompt_tokens = sum(e.prompt_tokens for e in step_costs)
        completion_tokens = sum(e.completion_tokens for e in step_costs)
        total_time_ms = int((end_time - start_time) * 1000) if end_time > start_time else 0

        # 从 BudgetAccount 补充数据（如果可用）
        model_name = ""
        if self._budget_account:
            try:
                task_cost = self._budget_account.get_task_cost(task_id)
                if task_cost.token_count > 0 and total_tokens == 0:
                    total_tokens = task_cost.token_count
            except Exception:
                pass

        if step_costs:
            model_name = step_costs[-1].model_name

        return CostTelemetry(
            trace_id=trace_id,
            total_tokens=total_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_time_ms=total_time_ms,
            total_steps=len(step_costs),
            retry_count=0,
            side_effect_intensity=dict(side_effects),
            model_name=model_name,
            step_cost_breakdown=list(step_costs),
        )

    def get_step_cost_breakdown(self, trace_id: str) -> List[StepCostEntry]:
        """获取 step 级别成本明细。"""
        return list(self._step_costs.get(trace_id, []))
