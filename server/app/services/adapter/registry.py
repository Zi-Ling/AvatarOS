"""AdapterRegistry — L1/L3 适配器注册表。"""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.adapter.base import NativeAdapter
from app.services.adapter.models import (
    AdapterSummary,
    AdapterType,
)


class AdapterAlreadyRegisteredError(Exception):
    """适配器名称重复注册时抛出。"""

    def __init__(self, adapter_name: str) -> None:
        super().__init__(f"适配器 '{adapter_name}' 已注册")
        self.adapter_name = adapter_name


class AdapterRegistry:
    """适配器注册表，管理所有已注册的 L1/L3 适配器。"""

    def __init__(self) -> None:
        self._adapters: dict[str, NativeAdapter] = {}
        self._registered_at: dict[str, datetime] = {}

    def register(self, adapter: NativeAdapter) -> None:
        name = adapter.adapter_name
        if name in self._adapters:
            raise AdapterAlreadyRegisteredError(name)
        self._adapters[name] = adapter
        self._registered_at[name] = datetime.now(timezone.utc)

    def unregister(self, adapter_name: str) -> None:
        self._adapters.pop(adapter_name, None)
        self._registered_at.pop(adapter_name, None)

    def get(self, adapter_name: str) -> NativeAdapter | None:
        return self._adapters.get(adapter_name)

    def lookup_by_capability(self, capability_name: str) -> list[NativeAdapter]:
        result: list[NativeAdapter] = []
        for adapter in self._adapters.values():
            schema = adapter.discover_capabilities()
            for op in schema.supported_operations:
                if op.operation_name == capability_name:
                    result.append(adapter)
                    break
        return result

    def lookup_by_type(self, adapter_type: AdapterType) -> list[NativeAdapter]:
        result: list[NativeAdapter] = []
        for adapter in self._adapters.values():
            schema = adapter.discover_capabilities()
            if schema.adapter_type == adapter_type:
                result.append(adapter)
        return result

    def list_all(self) -> list[AdapterSummary]:
        summaries: list[AdapterSummary] = []
        for name, adapter in self._adapters.items():
            schema = adapter.discover_capabilities()
            summaries.append(
                AdapterSummary(
                    name=name,
                    adapter_type=schema.adapter_type,
                    capabilities=[op.operation_name for op in schema.supported_operations],
                    registered_at=self._registered_at[name],
                )
            )
        return summaries
