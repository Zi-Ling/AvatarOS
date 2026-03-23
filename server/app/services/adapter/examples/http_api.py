"""http_api 适配器 — 通过 httpx 发送真实 HTTP 请求。"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

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

HTTP_API_SCHEMA = CapabilitySchema(
    adapter_name="http_api",
    adapter_type=AdapterType.L1,
    supported_operations=[
        OperationDef(
            operation_name="http_get",
            description="发送 HTTP GET 请求",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "headers": {"type": "object"},
                },
                "required": ["url"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "status_code": {"type": "integer"},
                    "body": {"type": "string"},
                    "headers": {"type": "object"},
                },
            },
            capability_class=CapabilityClass.NETWORK_STRUCTURED,
            side_effect_type=SideEffectType.READ,
            approval_default=SecurityLevel.ALLOWED,
        ),
        OperationDef(
            operation_name="http_post",
            description="发送 HTTP POST 请求",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "body": {},
                    "headers": {"type": "object"},
                },
                "required": ["url"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "status_code": {"type": "integer"},
                    "body": {"type": "string"},
                    "headers": {"type": "object"},
                },
            },
            capability_class=CapabilityClass.NETWORK_STRUCTURED,
            side_effect_type=SideEffectType.NETWORK_EGRESS,
            approval_default=SecurityLevel.APPROVAL_REQUIRED,
        ),
        OperationDef(
            operation_name="http_put",
            description="发送 HTTP PUT 请求",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "body": {},
                    "headers": {"type": "object"},
                },
                "required": ["url"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "status_code": {"type": "integer"},
                    "body": {"type": "string"},
                    "headers": {"type": "object"},
                },
            },
            capability_class=CapabilityClass.NETWORK_STRUCTURED,
            side_effect_type=SideEffectType.NETWORK_EGRESS,
            approval_default=SecurityLevel.APPROVAL_REQUIRED,
        ),
        OperationDef(
            operation_name="http_delete",
            description="发送 HTTP DELETE 请求",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "headers": {"type": "object"},
                },
                "required": ["url"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "status_code": {"type": "integer"},
                    "body": {"type": "string"},
                },
            },
            capability_class=CapabilityClass.NETWORK_STRUCTURED,
            side_effect_type=SideEffectType.DELETE,
            approval_default=SecurityLevel.APPROVAL_REQUIRED,
        ),
    ],
    version="1.0.0",
)


class HttpApiAdapter(NativeAdapter):
    """http_api 示例适配器。"""

    @property
    def adapter_name(self) -> str:
        return "http_api"

    def discover_capabilities(self) -> CapabilitySchema:
        return HTTP_API_SCHEMA

    def validate_params(self, operation_name: str, params: dict[str, Any]) -> ValidationResult:
        errors: list[str] = []
        op = next((o for o in HTTP_API_SCHEMA.supported_operations if o.operation_name == operation_name), None)
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
        url = validated_params["url"]
        headers = validated_params.get("headers") or {}
        body = validated_params.get("body")
        timeout = context.timeout_seconds

        method_map = {
            "http_get": "GET",
            "http_post": "POST",
            "http_put": "PUT",
            "http_delete": "DELETE",
        }
        method = method_map.get(operation_name)
        if not method:
            return NativeAdapterResult(
                success=False,
                error_code=NativeAdapterErrorCode.COMMAND_NOT_FOUND,
                error_message=f"未知操作: {operation_name}",
            )

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                kwargs: dict[str, Any] = {"headers": headers}
                if body is not None and method in ("POST", "PUT"):
                    if isinstance(body, (dict, list)):
                        kwargs["json"] = body
                    else:
                        kwargs["content"] = str(body)
                resp = await client.request(method, url, **kwargs)

            duration_ms = (time.monotonic() - start) * 1000
            return NativeAdapterResult(
                success=True,
                data={
                    "status_code": resp.status_code,
                    "body": resp.text,
                    "headers": dict(resp.headers),
                },
                duration_ms=duration_ms,
            )
        except httpx.TimeoutException:
            return NativeAdapterResult(
                success=False,
                error_code=NativeAdapterErrorCode.COMMAND_TIMEOUT,
                error_message=f"HTTP 请求超时 ({timeout}s): {url}",
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as exc:
            logger.warning(f"[HttpApiAdapter] {method} {url} failed: {exc}")
            return NativeAdapterResult(
                success=False,
                error_code=NativeAdapterErrorCode.COMMAND_FAILED,
                error_message=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )

    def collect_output(self, result: NativeAdapterResult) -> dict[str, Any]:
        return result.data if isinstance(result.data, dict) else {}
