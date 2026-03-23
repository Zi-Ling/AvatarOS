"""RoutingStepExecutor — 通过 Strategy Router 自动路由的 StepExecutor。"""

from __future__ import annotations

import time
import uuid
from typing import Any

from app.services.adapter.models import (
    ExecutionLayer,
    RiskLevel,
    TargetType,
)
from app.services.execution.models import ExecutionRequest
from app.services.execution.strategy_router import StrategyRouter
from app.services.workflow.models import WorkflowStepDef
from app.services.workflow.step_executor import (
    OutputContractValidator,
    StepExecutor,
    StepRunResult,
)


class RoutingStepExecutor(StepExecutor):
    """实现 StepExecutor 接口，通过 Strategy_Router 自动路由。"""

    def __init__(
        self,
        strategy_router: StrategyRouter,
        output_validator: OutputContractValidator,
    ) -> None:
        self._router = strategy_router
        self._output_validator = output_validator

    async def execute(
        self,
        step_def: WorkflowStepDef,
        resolved_inputs: dict[str, Any],
        instance_id: str,
    ) -> StepRunResult:
        start = time.perf_counter()
        params = step_def.params

        # 构造 ExecutionRequest
        req = ExecutionRequest(
            request_id=params.get("request_id", str(uuid.uuid4())),
            target_description=params.get("target_description", ""),
            target_type=TargetType(params.get("target_type", "unknown")),
            risk_level=RiskLevel(params.get("risk_level", "low")),
            allows_degradation=params.get("allows_degradation", True),
            allows_side_effects=params.get("allows_side_effects", True),
            constraints=params.get("constraints", {}),
            required_layer=(
                ExecutionLayer(params["required_layer"])
                if params.get("required_layer") else None
            ),
            preferred_layer=(
                ExecutionLayer(params["preferred_layer"])
                if params.get("preferred_layer") else None
            ),
            timeout_seconds=step_def.timeout_seconds,
            params=params,
        )

        result = await self._router.route_and_execute(req)
        duration = (time.perf_counter() - start) * 1000

        if result.success:
            outputs = dict(result.outputs)
            outputs["_routing_metadata"] = {
                "final_layer": result.final_layer.value,
                "degradation_path": [
                    {"from": e.source_layer.value, "to": e.target_layer.value}
                    for e in result.degradation_events
                ],
                "total_duration_ms": result.total_duration_ms,
            }
            run_result = StepRunResult(
                success=True, outputs=outputs, duration_ms=duration,
            )
            return self._output_validator.validate(step_def, run_result)

        return StepRunResult(
            success=False,
            error=result.error_message or "Routing execution failed",
            duration_ms=duration,
        )
