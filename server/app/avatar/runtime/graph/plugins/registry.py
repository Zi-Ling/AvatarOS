"""
Plugin Registry - Extensibility system for Graph Runtime

Provides decorators for registering skills, capabilities, and transformers
as plugins. Handles loading, validation, and graceful failure.

Requirements: 24.3, 24.4, 24.5, 24.6, 8.7, 28.8
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Type

logger = logging.getLogger(__name__)


class PluginLoadError(Exception):
    """Raised when a plugin fails to load."""
    pass


class PluginRegistry:
    """
    Central registry for Graph Runtime plugins.

    Supports three plugin types:
    - skill: primitive skill classes
    - capability: capability definitions
    - transformer: data transformer functions

    Requirements: 24.3, 24.4, 24.5, 24.6
    """

    def __init__(self):
        self._skills: Dict[str, Any] = {}
        self._capabilities: Dict[str, Any] = {}
        self._transformers: Dict[str, Callable] = {}
        self._load_errors: List[str] = []

    # ---- Registration ----

    def register_skill(self, name: str, skill_cls: Any) -> None:
        """Register a skill class. Requirements: 24.3"""
        if name in self._skills:
            logger.warning(f"[PluginRegistry] Skill '{name}' already registered, overwriting")
        self._skills[name] = skill_cls
        logger.info(f"[PluginRegistry] Registered skill: {name}")

    def register_capability(self, name: str, capability_def: Any) -> None:
        """Register a capability definition. Requirements: 24.4"""
        if name in self._capabilities:
            logger.warning(f"[PluginRegistry] Capability '{name}' already registered, overwriting")
        self._capabilities[name] = capability_def
        logger.info(f"[PluginRegistry] Registered capability: {name}")

    def register_transformer(self, name: str, fn: Callable) -> None:
        """Register a transformer function. Requirements: 24.5, 8.7"""
        if not callable(fn):
            raise PluginLoadError(f"Transformer '{name}' must be callable")
        if name in self._transformers:
            logger.warning(f"[PluginRegistry] Transformer '{name}' already registered, overwriting")
        self._transformers[name] = fn
        logger.info(f"[PluginRegistry] Registered transformer: {name}")

    # ---- Decorators ----

    def skill(self, name: str):
        """Decorator: @plugin_registry.skill('my.skill')"""
        def decorator(cls):
            try:
                self.register_skill(name, cls)
            except Exception as e:
                err = f"Failed to register skill '{name}': {e}"
                self._load_errors.append(err)
                logger.error(f"[PluginRegistry] {err}")
            return cls
        return decorator

    def capability(self, name: str):
        """Decorator: @plugin_registry.capability('my_capability')"""
        def decorator(fn_or_cls):
            try:
                self.register_capability(name, fn_or_cls)
            except Exception as e:
                err = f"Failed to register capability '{name}': {e}"
                self._load_errors.append(err)
                logger.error(f"[PluginRegistry] {err}")
            return fn_or_cls
        return decorator

    def transformer(self, name: str):
        """Decorator: @plugin_registry.transformer('my_transform')"""
        def decorator(fn: Callable):
            try:
                self.register_transformer(name, fn)
            except Exception as e:
                err = f"Failed to register transformer '{name}': {e}"
                self._load_errors.append(err)
                logger.error(f"[PluginRegistry] {err}")
            return fn
        return decorator

    # ---- Lookup ----

    def get_skill(self, name: str) -> Optional[Any]:
        return self._skills.get(name)

    def get_capability(self, name: str) -> Optional[Any]:
        return self._capabilities.get(name)

    def get_transformer(self, name: str) -> Optional[Callable]:
        return self._transformers.get(name)

    def list_skills(self) -> List[str]:
        return list(self._skills.keys())

    def list_capabilities(self) -> List[str]:
        return list(self._capabilities.keys())

    def list_transformers(self) -> List[str]:
        return list(self._transformers.keys())

    # ---- Validation ----

    def validate(self) -> Dict[str, Any]:
        """
        Validate all registered plugins.
        Returns summary with counts and any load errors.

        Requirements: 24.6
        """
        return {
            "skills": len(self._skills),
            "capabilities": len(self._capabilities),
            "transformers": len(self._transformers),
            "load_errors": list(self._load_errors),
            "valid": len(self._load_errors) == 0,
        }

    def apply_to_transformer_registry(self, transformer_registry: Dict[str, Callable]) -> None:
        """
        Apply registered transformers into an existing transformer_registry dict.
        Requirements: 8.7, 28.8
        """
        transformer_registry.update(self._transformers)
        logger.info(
            f"[PluginRegistry] Applied {len(self._transformers)} transformers "
            f"to transformer registry"
        )


# Global singleton
plugin_registry = PluginRegistry()


# Module-level decorator shortcuts
def register_skill(name: str):
    """Module-level decorator shortcut for skill registration."""
    return plugin_registry.skill(name)


def register_capability(name: str):
    """Module-level decorator shortcut for capability registration."""
    return plugin_registry.capability(name)


def register_transformer(name: str):
    """Module-level decorator shortcut for transformer registration."""
    return plugin_registry.transformer(name)
