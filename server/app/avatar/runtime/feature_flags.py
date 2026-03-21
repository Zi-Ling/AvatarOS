"""
Feature flags and capability checks for agent runtime modules.

P0 modules unavailable → P1+ modules degrade gracefully (no hard startup lock).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

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


def record_system_fallback(subsystem_name: str, error: Any, fallback_name: Optional[str] = None) -> None:
    """Unified fallback recording helper.

    Logs the fallback event and records it in the capability registry.
    Called when a subsystem degrades to its fallback implementation.
    """
    fb_label = fallback_name or "default_fallback"
    logger.warning(
        "[SystemFallback] subsystem='%s' error='%s' fallback='%s'",
        subsystem_name,
        error,
        fb_label,
    )


# All subsystem feature flags for the runtime
_SUBSYSTEM_FLAGS: list[str] = [
    "runtime_kernel",
    "agent_loop",
    "event_bus",
    "memory_system",
    "self_monitor",
    "policy_engine_v2",
    "action_plane",
    "collaboration_hub",
    "negotiation_engine",
    "task_scheduler",
    # Existing P0 modules
    "artifact_registry",
    "step_trace_store",
    "output_contract",
    "policy_engine",
    "budget_account",
]


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

    # Register new subsystem flags — probe importability
    new_subsystem_modules = {
        "runtime_kernel": "app.avatar.runtime.kernel.runtime_kernel",
        "agent_loop": "app.avatar.runtime.kernel.agent_loop",
        "event_bus": "app.avatar.runtime.events.bus",
        "memory_system": "app.avatar.memory.system",
        "self_monitor": "app.avatar.runtime.selfmonitor.self_monitor",
        "policy_engine_v2": "app.avatar.runtime.policy.policy_engine",
        "action_plane": "app.avatar.runtime.action_plane.action_plane",
        "collaboration_hub": "app.avatar.runtime.collaboration.collaboration_hub",
        "negotiation_engine": "app.avatar.runtime.negotiation.negotiation_engine",
        "task_scheduler": "app.avatar.runtime.scheduler.task_scheduler",
        "multi_agent_runtime": "app.avatar.runtime.multiagent",
    }
    for name, module_path in new_subsystem_modules.items():
        if name not in _registry._capabilities:
            try:
                __import__(module_path)
                _registry.register(name, True)
            except Exception as e:
                logger.debug(f"[CapabilityRegistry] Subsystem '{name}' not available: {e}")
                _registry.register(name, False)
