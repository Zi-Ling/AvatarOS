"""shell_command 示例适配器 — 高风险，默认 FORBIDDEN。"""

from __future__ import annotations

from typing import Any

from app.services.adapter.base import NativeAdapter
from app.services.adapter.models import (
    AdapterType,
    CapabilityClass,
    CapabilitySchema,
    ExecutionContext,
    NativeAdapterErrorCode,
    NativeAdapterResult,
    OperationDef,
    SecurityLevel,
    SideEffectType,
    ValidationResult,
)

SHELL_COMMAND_SCHEMA = CapabilitySchema(
    adapter_name="shell_command",
    adapter_type=AdapterType.L1,
    supported_operations=[
        OperationDef(
            operation_name="run_command",
            description="执行白名单中的 shell 命令",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "args": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["command"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "stdout": {"type": "string"},
                    "stderr": {"type": "string"},
                    "exit_code": {"type": "integer"},
                },
            },
            capability_class=CapabilityClass.COMMAND_EXEC,
            side_effect_type=SideEffectType.PROCESS_EXEC,
            approval_default=SecurityLevel.FORBIDDEN,
        ),
    ],
    version="1.0.0",
)


class ShellCommandAdapter(NativeAdapter):
    """shell_command 示例适配器 — 高风险 adapter，默认禁用。"""

    @property
    def adapter_name(self) -> str:
        return "shell_command"

    def discover_capabilities(self) -> CapabilitySchema:
        return SHELL_COMMAND_SCHEMA

    def validate_params(self, operation_name: str, params: dict[str, Any]) -> ValidationResult:
        errors: list[str] = []
        if operation_name != "run_command":
            return ValidationResult(valid=False, errors=[f"未知操作: {operation_name}"])
        if "command" not in params:
            errors.append("缺少必填参数: command")
        return ValidationResult(valid=len(errors) == 0, errors=errors)

    async def execute(
        self, operation_name: str, validated_params: dict[str, Any], context: ExecutionContext,
    ) -> NativeAdapterResult:
        return NativeAdapterResult(
            success=False,
            error_code=NativeAdapterErrorCode.SECURITY_BLOCKED,
            error_message="shell_command adapter: default FORBIDDEN",
        )

    def collect_output(self, result: NativeAdapterResult) -> dict[str, Any]:
        return result.data if isinstance(result.data, dict) else {}
