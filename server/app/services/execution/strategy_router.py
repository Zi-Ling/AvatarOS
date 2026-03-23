"""StrategyRouter — 统一执行路由编排器。"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable, Optional

from app.services.adapter.models import (
    AdapterType,
    ExecutionLayer,
    TargetType,
)
from app.services.adapter.registry import AdapterRegistry
from app.services.execution.config import RoutingConfig
from app.services.execution.models import (
    DegradationEvent,
    ExecutionAttempt,
    ExecutionRequest,
    ExecutionResult,
    RoutingDecision,
)

logger = logging.getLogger(__name__)

# 降级链顺序
DEGRADATION_CHAIN: list[ExecutionLayer] = [
    ExecutionLayer.L1_NATIVE,
    ExecutionLayer.L2_BROWSER,
    ExecutionLayer.L3_BRIDGE,
    ExecutionLayer.L4_COMPUTER_USE,
]


class RoutingMetrics:
    """路由指标聚合（内存计数器，线程安全）."""

    def __init__(self) -> None:
        self.route_count: dict[str, int] = defaultdict(int)
        self.success_count: dict[str, int] = defaultdict(int)
        self.failure_count: dict[str, int] = defaultdict(int)
        self.degradation_count: dict[str, int] = defaultdict(int)
        self.total_duration_ms: dict[str, float] = defaultdict(float)
        self._lock = asyncio.Lock()

    async def record_route(self, layer: ExecutionLayer) -> None:
        async with self._lock:
            self.route_count[layer.value] += 1

    async def record_success(self, layer: ExecutionLayer, duration_ms: float) -> None:
        async with self._lock:
            self.success_count[layer.value] += 1
            self.total_duration_ms[layer.value] += duration_ms

    async def record_failure(self, layer: ExecutionLayer) -> None:
        async with self._lock:
            self.failure_count[layer.value] += 1

    async def record_degradation(self, source: ExecutionLayer, target: ExecutionLayer) -> None:
        async with self._lock:
            key = f"{source.value}→{target.value}"
            self.degradation_count[key] += 1

    async def snapshot(self) -> dict[str, Any]:
        """返回当前指标快照."""
        async with self._lock:
            return {
                "routes": dict(self.route_count),
                "successes": dict(self.success_count),
                "failures": dict(self.failure_count),
                "degradations": dict(self.degradation_count),
                "avg_duration_ms": {
                    k: (self.total_duration_ms[k] / self.success_count[k])
                    if self.success_count.get(k) else 0
                    for k in self.route_count
                },
            }

class LayerResult:
    """单层执行结果（内部使用）。"""

    def __init__(
        self,
        success: bool,
        outputs: dict[str, Any] | None = None,
        error_code: str = "",
        error_message: str = "",
        degradable: bool = True,
        failure_context_json: str = "",
    ) -> None:
        self.success = success
        self.outputs = outputs or {}
        self.error_code = error_code
        self.error_message = error_message
        self.degradable = degradable
        self.failure_context_json = failure_context_json


# 层执行器类型签名
LayerExecutor = Callable[[ExecutionRequest], Awaitable[LayerResult]]


class StrategyRouter:
    """统一执行路由编排器。"""

    def __init__(
        self,
        adapter_registry: AdapterRegistry,
        config: RoutingConfig | None = None,
    ) -> None:
        self._registry = adapter_registry
        self._config = config or RoutingConfig()
        self._layer_executors: dict[ExecutionLayer, LayerExecutor] = {}
        self._metrics = RoutingMetrics()

    @property
    def metrics(self) -> RoutingMetrics:
        return self._metrics

    def register_layer_executor(
        self, layer: ExecutionLayer, executor: LayerExecutor,
    ) -> None:
        self._layer_executors[layer] = executor

    async def route_and_execute(self, request: ExecutionRequest) -> ExecutionResult:
        overall_start = time.perf_counter()
        selected = self._select_layer(request)
        alternatives = self._get_alternatives(selected, request)
        await self._metrics.record_route(selected)

        decision = RoutingDecision(
            request_id=request.request_id,
            selected_layer=selected,
            reason=self._build_reason(selected, request),
            alternatives=alternatives,
            timestamp=datetime.now(timezone.utc),
        )
        logger.info(
            "StrategyRouter routing: request_id=%s selected=%s reason=%s",
            request.request_id, selected.value, decision.reason,
        )

        attempts: list[ExecutionAttempt] = []
        degradation_events: list[DegradationEvent] = []
        current_layer = selected
        degradation_count = 0

        while current_layer is not None:
            attempt_start = time.perf_counter()
            attempt_start_dt = datetime.now(timezone.utc)

            executor = self._layer_executors.get(current_layer)
            if executor is None:
                # 无执行器，尝试下一层
                layer_result = LayerResult(
                    success=False,
                    error_code="NO_EXECUTOR",
                    error_message=f"No executor for {current_layer.value}",
                    degradable=True,
                )
            else:
                try:
                    layer_result = await executor(request)
                except Exception as exc:
                    layer_result = LayerResult(
                        success=False,
                        error_code="EXECUTOR_ERROR",
                        error_message=str(exc),
                        degradable=True,
                    )

            attempt_end = time.perf_counter()
            attempt = ExecutionAttempt(
                layer=current_layer,
                start_time=attempt_start_dt,
                end_time=datetime.now(timezone.utc),
                success=layer_result.success,
                result_summary=layer_result.error_message if not layer_result.success else "success",
                failure_context_json=layer_result.failure_context_json if not layer_result.success else None,
                duration_ms=(attempt_end - attempt_start) * 1000,
            )
            attempts.append(attempt)

            if layer_result.success:
                total_dur = (time.perf_counter() - overall_start) * 1000
                await self._metrics.record_success(current_layer, total_dur)
                return ExecutionResult(
                    success=True,
                    final_layer=current_layer,
                    outputs=layer_result.outputs,
                    attempts=attempts,
                    degradation_events=degradation_events,
                    routing_decision=decision,
                    total_duration_ms=total_dur,
                )

            # 检查是否可以降级
            can_degrade = (
                layer_result.degradable
                and request.allows_degradation
                and request.required_layer is None
                and degradation_count < self._config.max_degradation_steps
            )

            if not can_degrade:
                break

            next_layer = self._get_next_layer(current_layer)
            if next_layer is None:
                break

            # 检查降级路径是否被阻止
            if self._config.is_degradation_blocked(current_layer, next_layer):
                logger.info(
                    "StrategyRouter degradation blocked: %s→%s",
                    current_layer.value, next_layer.value,
                )
                break

            deg_event = DegradationEvent(
                source_layer=current_layer,
                target_layer=next_layer,
                error_code=layer_result.error_code,
                failure_reason=layer_result.error_message,
                failure_context_json=layer_result.failure_context_json or "{}",
                timestamp=datetime.now(timezone.utc),
            )
            degradation_events.append(deg_event)
            degradation_count += 1
            await self._metrics.record_degradation(current_layer, next_layer)

            logger.warning(
                "StrategyRouter degradation: request_id=%s %s→%s error=%s",
                request.request_id, current_layer.value, next_layer.value,
                layer_result.error_code,
            )
            current_layer = next_layer

        # 所有层失败
        total_dur = (time.perf_counter() - overall_start) * 1000
        final_layer = attempts[-1].layer if attempts else selected
        error_msg = attempts[-1].result_summary if attempts else "No layers available"
        await self._metrics.record_failure(final_layer)

        logger.error(
            "StrategyRouter all layers failed: request_id=%s degradation_chain=%s",
            request.request_id,
            "→".join(e.source_layer.value + "→" + e.target_layer.value for e in degradation_events),
        )

        return ExecutionResult(
            success=False,
            final_layer=final_layer,
            attempts=attempts,
            degradation_events=degradation_events,
            routing_decision=decision,
            total_duration_ms=total_dur,
            error_message=error_msg,
        )

    def _select_layer(self, request: ExecutionRequest) -> ExecutionLayer:
        """路由决策逻辑。"""
        # required_layer 强制
        if request.required_layer is not None:
            return request.required_layer

        # preferred_layer 优先
        if request.preferred_layer is not None:
            if request.preferred_layer not in self._config.disabled_layers:
                return request.preferred_layer

        # 自动选择：L1（有匹配适配器）→ L2（浏览器目标）→ L4（桌面应用/兜底）
        if ExecutionLayer.L1_NATIVE not in self._config.disabled_layers:
            # 检查是否有 L1 适配器能处理
            adapter_name = request.params.get("adapter_name", "")
            if adapter_name and self._registry.get(adapter_name):
                return ExecutionLayer.L1_NATIVE
            # 检查 target_type 是否匹配 L1
            if request.target_type in (
                TargetType.FILE_OPERATION,
                TargetType.API_CALL,
                TargetType.SHELL_COMMAND,
            ):
                l1_adapters = self._registry.lookup_by_type(AdapterType.L1)
                if l1_adapters:
                    return ExecutionLayer.L1_NATIVE

        if ExecutionLayer.L2_BROWSER not in self._config.disabled_layers:
            if request.target_type == TargetType.BROWSER_INTERACTION:
                return ExecutionLayer.L2_BROWSER

        # DESKTOP_APP 显式路由到 L4
        if request.target_type == TargetType.DESKTOP_APP:
            if ExecutionLayer.L4_COMPUTER_USE not in self._config.disabled_layers:
                return ExecutionLayer.L4_COMPUTER_USE

        if ExecutionLayer.L4_COMPUTER_USE not in self._config.disabled_layers:
            return ExecutionLayer.L4_COMPUTER_USE

        # 所有层都被禁用，返回 L4 作为最后手段
        return ExecutionLayer.L4_COMPUTER_USE

    def _get_next_layer(self, current_layer: ExecutionLayer) -> ExecutionLayer | None:
        """返回降级链中的下一层，跳过禁用层和无适配器的 L3。"""
        try:
            idx = DEGRADATION_CHAIN.index(current_layer)
        except ValueError:
            return None

        for next_layer in DEGRADATION_CHAIN[idx + 1:]:
            if next_layer in self._config.disabled_layers:
                continue
            # L3 无适配器时跳过
            if next_layer == ExecutionLayer.L3_BRIDGE:
                l3_adapters = self._registry.lookup_by_type(AdapterType.L3)
                if not l3_adapters:
                    continue
            return next_layer
        return None

    def _get_alternatives(
        self, selected: ExecutionLayer, request: ExecutionRequest,
    ) -> list[ExecutionLayer]:
        """获取备选执行层列表。"""
        alts: list[ExecutionLayer] = []
        for layer in DEGRADATION_CHAIN:
            if layer == selected:
                continue
            if layer in self._config.disabled_layers:
                continue
            if layer == ExecutionLayer.L3_BRIDGE:
                l3_adapters = self._registry.lookup_by_type(AdapterType.L3)
                if not l3_adapters:
                    continue
            alts.append(layer)
        return alts

    def _build_reason(self, selected: ExecutionLayer, request: ExecutionRequest) -> str:
        if request.required_layer is not None:
            return f"required_layer={selected.value}"
        if request.preferred_layer is not None and selected == request.preferred_layer:
            return f"preferred_layer={selected.value}"
        if selected == ExecutionLayer.L1_NATIVE:
            return "L1 adapter available for target"
        if selected == ExecutionLayer.L2_BROWSER:
            return "browser interaction target"
        if selected == ExecutionLayer.L4_COMPUTER_USE and request.target_type == TargetType.DESKTOP_APP:
            return "desktop app target → L4"
        return f"fallback to {selected.value}"
