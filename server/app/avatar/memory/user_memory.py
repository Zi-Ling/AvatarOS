from __future__ import annotations

"""UserMemory — user-level minimal profile.

V1: communication_style + approval_patterns + quality_expectations.
V2_PLANNED: feedback_history, schedule_preferences.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class UserMemory:
    """User-level minimal profile."""

    communication_style: str = "technical"
    approval_patterns: dict[str, str] = field(default_factory=dict)
    quality_expectations: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0.0"
    # V2_PLANNED: feedback_history: list[dict[str, Any]]
    # V2_PLANNED: schedule_preferences: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "communication_style": self.communication_style,
            "approval_patterns": dict(self.approval_patterns),
            "quality_expectations": dict(self.quality_expectations),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserMemory:
        return cls(
            communication_style=data.get("communication_style", "technical"),
            approval_patterns=dict(data.get("approval_patterns") or {}),
            quality_expectations=dict(data.get("quality_expectations") or {}),
            schema_version=data.get("schema_version", "1.0.0"),
        )
