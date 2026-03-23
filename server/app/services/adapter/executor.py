"""NativeAdapterStepExecutor — 将 workflow step 委托给 L1 适配器执行。"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.services.adapter.models import (
    AdapterFailureContext,
    ExecutionContext,
    NativeAdapterErrorCode,
    NativeAdapterResult,
    NATIVE_ADAPTER_ERROR_DEGRADABLE,
    SecurityLevel,
)
from app.services.adapter.registry import AdapterRegistry
from app.services.adapter.security_policy import SecurityPolicy
from app.services.workflow.models import WorkflowStepDef
from app.services.workflow.step_executor import (
    OutputContractValidator,
    StepExecutor,
    StepRunResult,
)

logger = logging.getLogger(__name__)


class NativeAdapterStepExecutor(StepExecutor):
    """实现 StepExecutor 接口，将 workflow step 委托给 L1 适配器执行。"""

    def __init__(
        self,
        registry: AdapterRegistry,
        security_policy: SecurityPolicy,
        output_validator: OutputContractValidator,
        approval_func=None,
    ) -> None:
        self._registry = registry
        self._security_policy = security_policy
        self._output_validator = output_validator
        self._approval_func = approval_func

    async def execute(
        self,
        step_def: WorkflowStepDef,
        resolved_inputs: dict[str, Any],
        instance_id: str,
    ) -> StepRunResult:
        start = time.perf_counter()
        adapter_name = step_def.params.get("adapter_name", "")
        operation_name = step_def.params.get("operation_name", "")
        operation_params = step_def.params.get("operation_params", {})
        # merge resolved_inputs into operation_params
        merged_params = {**operation_params, **resolved_inputs}

        try:
            # 1. Security check
            adapter = self._registry.get(adapter_name)
            default_level = SecurityLevel.ALLOWED
            if adapter:
                schema = adapter.discover_capabilities()
                for op in schema.supported_operations:
                    if op.operation_name == operation_name:
                        default_level = op.approval_default
                        break

            level = self._security_policy.classify(adapter_name, operation_name, default=default_level)

            if level == SecurityLevel.FORBIDDEN:
                return self._fail(
                    adapter_name, operation_name,
                    NativeAdapterErrorCode.SECURITY_BLOCKED,
                    "操作被安全策略禁止", start,
                )

            if level == SecurityLevel.APPROVAL_REQUIRED:
                approved = await self._request_approval(adapter_name, operation_name)
                if not approved:
                    return self._fail(
                        adapter_name, operation_name,
                        NativeAdapterErrorCode.APPROVAL_TIMEOUT,
                        "审批超时", start,
                    )

            # 2. Get adapter
            if adapter is None:
                return self._fail(
                    adapter_name, operation_name,
                    NativeAdapterErrorCode.ADAPTER_NOT_FOUND,
                    f"适配器 '{adapter_name}' 未找到", start,
                )

            # 3. Validate params
            validation = adapter.validate_params(operation_name, merged_params)
            if not validation.valid:
                return self._fail(
                    adapter_name, operation_name,
                    NativeAdapterErrorCode.INVALID_PARAMS,
                    f"参数校验失败: {'; '.join(validation.errors)}", start,
                )

            # 4. Execute
            context = ExecutionContext(
                instance_id=instance_id,
                timeout_seconds=step_def.timeout_seconds,
            )
            result: NativeAdapterResult = await adapter.execute(
                operation_name, merged_params, context,
            )

            if not result.success:
                error_code = result.error_code or NativeAdapterErrorCode.UNKNOWN
                return self._fail(
                    adapter_name, operation_name,
                    error_code,
                    result.error_message or "执行失败", start,
                )

            # 5. Collect output
            outputs = adapter.collect_output(result)

            # 6. Output contract validation
            duration = (time.perf_counter() - start) * 1000
            run_result = StepRunResult(success=True, outputs=outputs, duration_ms=duration)
            run_result = self._output_validator.validate(step_def, run_result)

            self._audit_log(adapter_name, operation_name, level, run_result)
            return run_result

        except Exception as exc:
            logger.exception(f"NativeAdapterStepExecutor unexpected error: {exc}")
            return self._fail(
                adapter_name, operation_name,
                NativeAdapterErrorCode.UNKNOWN,
                str(exc), start,
            )

    def _fail(
        self,
        adapter_name: str,
        operation_name: str,
        error_code: NativeAdapterErrorCode,
        error_message: str,
        start: float,
    ) -> StepRunResult:
        duration = (time.perf_counter() - start) * 1000
        ctx = AdapterFailureContext(
            error_code=error_code,
            error_message=error_message,
            degradable=NATIVE_ADAPTER_ERROR_DEGRADABLE.get(error_code, True),
            adapter_name=adapter_name,
            operation_name=operation_name,
        )
        return StepRunResult(
            success=False,
            error=ctx.to_json(),
            duration_ms=duration,
        )

    async def _request_approval(self, adapter_name: str, operation_name: str) -> bool:
        if self._approval_func is None:
            return False
        timeout = self._security_policy.approval_timeout_seconds
        try:
            return await asyncio.wait_for(
                self._approval_func(adapter_name, operation_name),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return False

    def _audit_log(
        self,
        adapter_name: str,
        operation_name: str,
        level: SecurityLevel,
        result: StepRunResult,
    ) -> None:
        logger.info(
            "NativeAdapterStepExecutor audit: adapter=%s operation=%s "
            "security_level=%s success=%s",
            adapter_name, operation_name, level.value, result.success,
        )
