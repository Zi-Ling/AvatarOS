"""SecurityPolicy — L1 适配器安全策略，三级分类。"""

from __future__ import annotations

from app.services.adapter.models import (
    SecurityLevel,
    SecurityPolicyConfig,
)


class SecurityPolicy:
    """L1 适配器安全策略。

    支持两种模式：
    - 默认模式：使用 OperationDef.approval_default 作为基线，overrides 覆盖
    - 白名单模式：未在白名单中的命令默认 FORBIDDEN
    """

    def __init__(self) -> None:
        self._overrides: dict[str, dict[str, SecurityLevel]] = {}
        self._whitelist_mode: bool = False
        self._whitelisted_commands: set[str] = set()
        self._approval_timeout_seconds: int = 60

    def load_from_config(self, config: SecurityPolicyConfig) -> None:
        self._overrides = dict(config.overrides)
        self._whitelist_mode = config.whitelist_mode
        self._whitelisted_commands = set(config.whitelisted_commands)
        self._approval_timeout_seconds = config.approval_timeout_seconds

    @property
    def approval_timeout_seconds(self) -> int:
        return self._approval_timeout_seconds

    def classify(
        self,
        adapter_name: str,
        operation_name: str,
        default: SecurityLevel = SecurityLevel.ALLOWED,
    ) -> SecurityLevel:
        # 白名单模式：未在白名单中的命令默认 FORBIDDEN
        if self._whitelist_mode:
            cmd_key = f"{adapter_name}.{operation_name}"
            if cmd_key not in self._whitelisted_commands:
                return SecurityLevel.FORBIDDEN

        # overrides 优先
        adapter_overrides = self._overrides.get(adapter_name)
        if adapter_overrides and operation_name in adapter_overrides:
            return adapter_overrides[operation_name]

        return default
