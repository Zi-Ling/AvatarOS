"""NativeAdapter 抽象基类 — L1 适配器标准接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.services.adapter.models import (
    CapabilitySchema,
    ExecutionContext,
    NativeAdapterResult,
    ValidationResult,
)


class NativeAdapter(ABC):
    """L1 Native Adapter 标准接口，所有适配器必须实现。"""

    @property
    @abstractmethod
    def adapter_name(self) -> str:
        """适配器唯一名称。"""

    @abstractmethod
    def discover_capabilities(self) -> CapabilitySchema:
        """返回该适配器支持的能力声明。"""

    @abstractmethod
    def validate_params(self, operation_name: str, params: dict[str, Any]) -> ValidationResult:
        """
        校验操作参数。
        返回 ValidationResult，失败时包含所有校验错误（非仅第一个）。
        """

    @abstractmethod
    async def execute(
        self,
        operation_name: str,
        validated_params: dict[str, Any],
        context: ExecutionContext,
    ) -> NativeAdapterResult:
        """执行操作，返回标准化结果。不含任何降级逻辑。"""

    @abstractmethod
    def collect_output(self, result: NativeAdapterResult) -> dict[str, Any]:
        """从执行结果中提取结构化输出。"""
