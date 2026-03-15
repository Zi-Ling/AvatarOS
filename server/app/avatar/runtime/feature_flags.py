"""
Feature flags and capability checks for agent runtime modules.

P0 modules unavailable → P1+ modules degrade gracefully (no hard startup lock).
"""
from __future__ import annotations

import logging
from typing import Dict

logger = logging.getLogger(__name__)


class CapabilityRegistry:
    """
    Tracks which runtime modules are available.
    P1+ modules check P0 availability and degrade if not ready.
    """

    def __init__(self) -> None:
        self._capabilities: Dict[str, bool] = {}

    def register(self, name: str, available: bool) -> None:
        self._capabilities[name] = available
        if not available:
            logger.warning(f"[CapabilityRegistry] Module '{name}' is NOT available — dependent modules will degrade")

    def is_available(self, name: str) -> bool:
        return self._capabilities.get(name, False)

    def check_or_warn(self, name: str, dependent: str) -> bool:
        """Check if a dependency is available; warn if not (no exception)."""
        if not self.is_available(name):
            logger.warning(
                f"[CapabilityRegistry] '{dependent}' requires '{name}' which is not available — degrading"
            )
            return False
        return True


# Global singleton
_registry = CapabilityRegistry()


def get_capability_registry() -> CapabilityRegistry:
    return _registry


def probe_modules() -> None:
    """
    Probe all P0 modules and register their availability.
    Called at startup — never raises.
    """
    modules = {
        "artifact_registry": "app.avatar.runtime.artifact.registry",
        "step_trace_store": "app.avatar.runtime.graph.storage.step_trace_store",
        "output_contract": "app.avatar.runtime.graph.models.output_contract",
        "policy_engine": "app.avatar.runtime.policy.policy_engine",
        "budget_account": "app.avatar.runtime.policy.budget_account",
    }
    for name, module_path in modules.items():
        try:
            __import__(module_path)
            _registry.register(name, True)
        except Exception as e:
            logger.warning(f"[CapabilityRegistry] Failed to import {module_path}: {e}")
            _registry.register(name, False)
