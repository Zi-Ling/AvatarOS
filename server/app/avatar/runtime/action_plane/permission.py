"""PermissionTier — four-level permission model for ActionPlane.

Requirement: 8.3
"""
from __future__ import annotations

from enum import Enum


class PermissionTier(str, Enum):
    """Four-level permission model for action execution governance."""

    READ_ONLY = "read_only"
    WRITE_SAFE = "write_safe"
    WRITE_DESTRUCTIVE = "write_destructive"
    ADMIN = "admin"

    # ── comparison helpers ──

    def __ge__(self, other: PermissionTier) -> bool:  # type: ignore[override]
        if not isinstance(other, PermissionTier):
            return NotImplemented
        return _TIER_ORDER[self] >= _TIER_ORDER[other]

    def __gt__(self, other: PermissionTier) -> bool:  # type: ignore[override]
        if not isinstance(other, PermissionTier):
            return NotImplemented
        return _TIER_ORDER[self] > _TIER_ORDER[other]

    def __le__(self, other: PermissionTier) -> bool:  # type: ignore[override]
        if not isinstance(other, PermissionTier):
            return NotImplemented
        return _TIER_ORDER[self] <= _TIER_ORDER[other]

    def __lt__(self, other: PermissionTier) -> bool:  # type: ignore[override]
        if not isinstance(other, PermissionTier):
            return NotImplemented
        return _TIER_ORDER[self] < _TIER_ORDER[other]


# Ordering map: higher value = more privileged
_TIER_ORDER: dict[PermissionTier, int] = {
    PermissionTier.READ_ONLY: 0,
    PermissionTier.WRITE_SAFE: 1,
    PermissionTier.WRITE_DESTRUCTIVE: 2,
    PermissionTier.ADMIN: 3,
}
