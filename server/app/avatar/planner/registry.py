# avatar/planner/registry.py
from __future__ import annotations

from typing import Any, Dict, Optional, Type

from .base import TaskPlanner


# Global registry: planner_name -> TaskPlanner class
_PLANNER_REGISTRY: Dict[str, Type[TaskPlanner]] = {}

# Optional mapping from intent_type -> planner_name
_INTENT_PLANNER_MAP: Dict[str, str] = {}


def register_planner(name: str, planner_cls: Type[TaskPlanner]) -> None:
    """
    Register a TaskPlanner implementation under a given name.

    Typically called at import time in the module that defines the planner, e.g.:

        from .registry import register_planner

        class SimpleLLMPlanner(TaskPlanner):
            ...

        register_planner("simple_llm", SimpleLLMPlanner)
    """
    if not name:
        raise ValueError("Planner name must be a non-empty string.")
    _PLANNER_REGISTRY[name] = planner_cls


def planner_registered(name: str) -> bool:
    """
    Check whether a planner with the given name is registered.
    """
    return name in _PLANNER_REGISTRY


def get_planner_class(name: str) -> Type[TaskPlanner]:
    """
    Return the TaskPlanner class registered under `name`.

    This does NOT instantiate the planner; you are free to pass any
    constructor arguments when you instantiate it.
    """
    try:
        return _PLANNER_REGISTRY[name]
    except KeyError:
        raise KeyError(f"No TaskPlanner registered under name '{name}'.") from None


def create_planner(name: str, **kwargs: Any) -> TaskPlanner:
    """
    Convenience helper: instantiate a TaskPlanner by name.

    Example:
        planner = create_planner("simple_llm", llm_client=..., logger=...)
    """
    planner_cls = get_planner_class(name)
    return planner_cls(**kwargs)  # type: ignore[call-arg]


def register_intent_mapping(intent_type: str, planner_name: str) -> None:
    """
    Associate a logical `intent_type` with a planner name.

    This is optional sugar to let you route different intent types to
    different planning strategies.

    Example:
        register_intent_mapping("web_automation", "simple_llm")
        register_intent_mapping("file_batch", "rule_based")
    """
    if not intent_type:
        raise ValueError("intent_type must be a non-empty string.")
    if planner_name not in _PLANNER_REGISTRY:
        raise ValueError(
            f"Planner '{planner_name}' is not registered; register it before mapping intent types."
        )
    _INTENT_PLANNER_MAP[intent_type] = planner_name


def get_planner_for_intent(
    intent_type: str,
    *,
    default_planner_name: Optional[str] = None,
    **kwargs: Any,
) -> TaskPlanner:
    """
    Select and instantiate a TaskPlanner based on the intent_type.

    Resolution order:
        1. If intent_type is mapped in _INTENT_PLANNER_MAP, use that planner_name.
        2. Else, if default_planner_name is provided and registered, use that.
        3. Else, raise KeyError.

    Example:
        planner = get_planner_for_intent(
            intent.intent_type,
            default_planner_name="simple_llm",
            llm_client=...,
        )
    """
    planner_name = _INTENT_PLANNER_MAP.get(intent_type)

    if planner_name is not None:
        return create_planner(planner_name, **kwargs)

    if default_planner_name is not None:
        if default_planner_name not in _PLANNER_REGISTRY:
            raise KeyError(
                f"default_planner_name '{default_planner_name}' is not registered."
            )
        return create_planner(default_planner_name, **kwargs)

    raise KeyError(
        f"No planner mapping found for intent_type '{intent_type}', "
        f"and no default_planner_name was provided."
    )
