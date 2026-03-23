# app/services/computer/__init__.py
"""Computer Use Runtime — desktop autonomous control sub-executor.

Uses lazy imports to avoid circular dependency with app.avatar.skills.
"""


def __getattr__(name: str):
    """Lazy import to break circular import chain."""
    from .models import (
        DominantLayout,
        ActionType,
        ClickType,
        ScrollDirection,
        FallbackStrategy,
        VerificationStrategy,
        TransitionType,
        StuckType,
        LocatorSource,
        OperationLevel,
        VerificationVerdict,
        FormFieldType,
        GUIState,
        ObservationBundle,
        LocatorCandidate,
        LocatorResult,
        ActionPlan,
        ActionResult,
        VerificationResult,
        TransitionVerdict,
        ComputerUseSessionState,
        OTAVResult,
        ComputerUseResult,
        ComputerUseConfig,
    )

    _exports = {
        "DominantLayout": DominantLayout,
        "ActionType": ActionType,
        "ClickType": ClickType,
        "ScrollDirection": ScrollDirection,
        "FallbackStrategy": FallbackStrategy,
        "VerificationStrategy": VerificationStrategy,
        "TransitionType": TransitionType,
        "StuckType": StuckType,
        "LocatorSource": LocatorSource,
        "OperationLevel": OperationLevel,
        "VerificationVerdict": VerificationVerdict,
        "FormFieldType": FormFieldType,
        "GUIState": GUIState,
        "ObservationBundle": ObservationBundle,
        "LocatorCandidate": LocatorCandidate,
        "LocatorResult": LocatorResult,
        "ActionPlan": ActionPlan,
        "ActionResult": ActionResult,
        "VerificationResult": VerificationResult,
        "TransitionVerdict": TransitionVerdict,
        "ComputerUseSessionState": ComputerUseSessionState,
        "OTAVResult": OTAVResult,
        "ComputerUseResult": ComputerUseResult,
        "ComputerUseConfig": ComputerUseConfig,
    }

    if name in _exports:
        return _exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "DominantLayout",
    "ActionType",
    "ClickType",
    "ScrollDirection",
    "FallbackStrategy",
    "VerificationStrategy",
    "TransitionType",
    "StuckType",
    "LocatorSource",
    "OperationLevel",
    "VerificationVerdict",
    "FormFieldType",
    "GUIState",
    "ObservationBundle",
    "LocatorCandidate",
    "LocatorResult",
    "ActionPlan",
    "ActionResult",
    "VerificationResult",
    "TransitionVerdict",
    "ComputerUseSessionState",
    "OTAVResult",
    "ComputerUseResult",
    "ComputerUseConfig",
]
