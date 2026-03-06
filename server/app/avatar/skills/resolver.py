# app/avatar/skills/resolver.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .base import SkillSpec, BaseSkill
    from .registry import SkillRegistry


@dataclass
class ResolveResult:
    skill_cls: Optional[type[BaseSkill]]
    spec: Optional[SkillSpec]
    reason: str
    normalized_name: str
    matched_as: str  # "exact" / "alias" / "not_found"


class ToolResolver:
    """
    Resolves tool names (from LLM/Planner) to skill classes via SkillRegistry.
    Supports exact name match and alias match.
    """

    def __init__(self, registry: SkillRegistry):
        self.registry = registry

    def resolve(self, raw_name: str) -> ResolveResult:
        name = raw_name.strip()

        cls = self.registry.get(name)
        if cls:
            matched_as = "exact" if name == cls.spec.name else "alias"
            return ResolveResult(
                skill_cls=cls,
                spec=cls.spec,
                reason=f"Matched {matched_as}={name}",
                normalized_name=cls.spec.name,
                matched_as=matched_as,
            )

        return ResolveResult(
            skill_cls=None,
            spec=None,
            reason=f"Tool not found: {name}",
            normalized_name=name,
            matched_as="not_found",
        )
