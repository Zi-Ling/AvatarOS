"""file_system 适配器 — 真实文件系统操作。"""

from __future__ import annotations

import logging
import time
from pathlib import Path
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

logger = logging.getLogger(__name__)

FILE_SYSTEM_SCHEMA = CapabilitySchema(
    adapter_name="file_system",
    adapter_type=AdapterType.L1,
    supported_operations=[
        OperationDef(
            operation_name="read_file",
            description="读取文件内容",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "size": {"type": "integer"},
                },
            },
            capability_class=CapabilityClass.LOCAL_STRUCTURED,
            side_effect_type=SideEffectType.READ,
            approval_default=SecurityLevel.ALLOWED,
        ),
        OperationDef(
            operation_name="write_file",
            description="写入文件内容",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            output_schema={
                "type": "object",
                "properties": {"bytes_written": {"type": "integer"}},
            },
            capability_class=CapabilityClass.LOCAL_STRUCTURED,
            side_effect_type=SideEffectType.WRITE,
            approval_default=SecurityLevel.APPROVAL_REQUIRED,
        ),
        OperationDef(
            operation_name="list_directory",
            description="列出目录内容",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "entries": {"type": "array", "items": {"type": "string"}},
                },
            },
            capability_class=CapabilityClass.LOCAL_STRUCTURED,
            side_effect_type=SideEffectType.READ,
            approval_default=SecurityLevel.ALLOWED,
        ),
        OperationDef(
            operation_name="delete_file",
            description="删除文件",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            output_schema={
                "type": "object",
                "properties": {"deleted": {"type": "boolean"}},
            },
            capability_class=CapabilityClass.LOCAL_STRUCTURED,
            side_effect_type=SideEffectType.DELETE,
            approval_default=SecurityLevel.APPROVAL_REQUIRED,
        ),
    ],
    version="1.0.0",
)


class FileSystemAdapter(NativeAdapter):
    """file_system 示例适配器。"""

    @property
    def adapter_name(self) -> str:
        return "file_system"

    def discover_capabilities(self) -> CapabilitySchema:
        return FILE_SYSTEM_SCHEMA

    def validate_params(self, operation_name: str, params: dict[str, Any]) -> ValidationResult:
        errors: list[str] = []
        schema = FILE_SYSTEM_SCHEMA
        op = next((o for o in schema.supported_operations if o.operation_name == operation_name), None)
        if op is None:
            return ValidationResult(valid=False, errors=[f"未知操作: {operation_name}"])
        required = op.input_schema.get("required", [])
        for key in required:
            if key not in params:
                errors.append(f"缺少必填参数: {key}")
        return ValidationResult(valid=len(errors) == 0, errors=errors)

    async def execute(
        self, operation_name: str, validated_params: dict[str, Any], context: ExecutionContext,
    ) -> NativeAdapterResult:
        start = time.monotonic()
        # 安全检查：限制在 working_directory 内操作
        base_dir = Path(context.working_directory) if context.working_directory else Path.cwd()
        target = (base_dir / validated_params["path"]).resolve()
        if not str(target).startswith(str(base_dir.resolve())):
            return NativeAdapterResult(
                success=False,
                error_code=NativeAdapterErrorCode.PERMISSION_DENIED,
                error_message=f"路径越界: {validated_params['path']}",
            )

        try:
            if operation_name == "read_file":
                content = target.read_text(encoding="utf-8")
                return NativeAdapterResult(
                    success=True,
                    data={"content": content, "size": len(content.encode("utf-8"))},
                    duration_ms=(time.monotonic() - start) * 1000,
                )
            elif operation_name == "write_file":
                target.parent.mkdir(parents=True, exist_ok=True)
                text = validated_params["content"]
                target.write_text(text, encoding="utf-8")
                return NativeAdapterResult(
                    success=True,
                    data={"bytes_written": len(text.encode("utf-8"))},
                    duration_ms=(time.monotonic() - start) * 1000,
                )
            elif operation_name == "list_directory":
                entries = [e.name for e in target.iterdir()]
                return NativeAdapterResult(
                    success=True,
                    data={"entries": sorted(entries)},
                    duration_ms=(time.monotonic() - start) * 1000,
                )
            elif operation_name == "delete_file":
                existed = target.exists()
                if existed:
                    target.unlink()
                return NativeAdapterResult(
                    success=True,
                    data={"deleted": existed},
                    duration_ms=(time.monotonic() - start) * 1000,
                )
            else:
                return NativeAdapterResult(
                    success=False,
                    error_code=NativeAdapterErrorCode.COMMAND_NOT_FOUND,
                    error_message=f"未知操作: {operation_name}",
                )
        except PermissionError as exc:
            return NativeAdapterResult(
                success=False,
                error_code=NativeAdapterErrorCode.PERMISSION_DENIED,
                error_message=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except FileNotFoundError as exc:
            return NativeAdapterResult(
                success=False,
                error_code=NativeAdapterErrorCode.COMMAND_FAILED,
                error_message=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as exc:
            logger.warning(f"[FileSystemAdapter] {operation_name} failed: {exc}")
            return NativeAdapterResult(
                success=False,
                error_code=NativeAdapterErrorCode.COMMAND_FAILED,
                error_message=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )

    def collect_output(self, result: NativeAdapterResult) -> dict[str, Any]:
        return result.data if isinstance(result.data, dict) else {}
