"""RoutingConfig — Strategy Router 配置模型。"""

from __future__ import annotations

from pydantic import BaseModel

from app.services.adapter.models import ExecutionLayer


# 不允许降级的 (source, target) 对 — 用户可配置
# 默认不阻止任何降级路径，因为降级链路中经过的中间层不应被阻止
_BLOCKED_DEGRADATION_PAIRS: set[tuple[ExecutionLayer, ExecutionLayer]] = set()


class RoutingConfig(BaseModel):
    """Strategy Router 配置"""
    max_degradation_steps: int = 3
    disabled_layers: list[ExecutionLayer] = []
    default_timeout_seconds: int = 300
    # 每层超时（覆盖 default_timeout_seconds）
    layer_timeout_seconds: dict[str, int] = {}
    # 被阻止的降级路径
    blocked_degradation_pairs: set[tuple[str, str]] = set()

    def is_degradation_blocked(
        self, source: ExecutionLayer, target: ExecutionLayer,
    ) -> bool:
        """检查降级路径是否被阻止."""
        # 检查内置阻止规则
        if (source, target) in _BLOCKED_DEGRADATION_PAIRS:
            return True
        # 检查用户配置的阻止规则
        return (source.value, target.value) in self.blocked_degradation_pairs
