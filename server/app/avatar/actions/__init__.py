# app/avatar/actions/__init__.py
"""
Action subsystem scaffolding.

The runtime does not call these objects yet, but defining the public surface
now keeps future integrations consistent with other Avatar components.
"""

from .base import Action, ActionContext, ActionResult

__all__ = [
    "Action",
    "ActionContext",
    "ActionResult",
]
