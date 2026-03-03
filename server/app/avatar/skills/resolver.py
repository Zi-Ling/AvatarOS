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
    matched_as: str   # "api" / "alias" / "internal" / "fuzzy" / "not_found"

class ToolResolver:
    """
    Unified tool name resolver.
    Decouples external tool names (from LLM/Planner) from internal implementation names.
    """

    def __init__(self, registry: SkillRegistry, enable_fuzzy: bool = False):
        self.registry = registry
        self.enable_fuzzy = enable_fuzzy

    def resolve(self, raw_name: str) -> ResolveResult:
        name = raw_name.strip()

        # 1. Exact Match: API Name
        # Using registry's internal index which maps api_name -> internal_name -> skill_cls
        internal_name = self.registry.get_internal_name_by_api(name)
        if internal_name:
            cls = self.registry.get_by_internal(internal_name)
            if cls:
                return ResolveResult(
                    skill_cls=cls,
                    spec=cls.spec,
                    reason=f"Matched api_name={name}",
                    normalized_name=name,
                    matched_as="api",
                )

        # 2. Exact Match: Alias
        internal_name = self.registry.get_internal_name_by_alias(name)
        if internal_name:
            cls = self.registry.get_by_internal(internal_name)
            if cls:
                return ResolveResult(
                    skill_cls=cls,
                    spec=cls.spec,
                    reason=f"Matched alias={name} -> internal={internal_name}",
                    normalized_name=cls.spec.api_name,
                    matched_as="alias",
                )

        # 3. Exact Match: Internal Name (Fallback)
        cls = self.registry.get_by_internal(name)
        if cls:
            return ResolveResult(
                skill_cls=cls,
                spec=cls.spec,
                reason=f"Matched internal_name={name}",
                normalized_name=cls.spec.api_name,
                matched_as="internal",
            )

        # 4. Fuzzy Match (Optional)
        if self.enable_fuzzy:
            # TODO: Implement Levenshtein distance or embedding match
            # For now, simple prefix match
            lowered = name.lower()
            for cls in self.registry.iter_skills():
                spec = cls.spec
                if spec.api_name.lower().startswith(lowered.split(".")[0]):
                     # Only if it's a strong match (e.g. 'file' matches 'file.write') - NO, that's too weak.
                     # How about: 'file.write' matches 'file.write_text'
                     if spec.api_name.lower().startswith(lowered): 
                         return ResolveResult(
                            skill_cls=cls,
                            spec=spec,
                            reason=f"Fuzzy prefix match {name} -> {spec.api_name}",
                            normalized_name=spec.api_name,
                            matched_as="fuzzy",
                        )

        # 5. Not Found
        return ResolveResult(
            skill_cls=None,
            spec=None,
            reason=f"Tool not found: {name}",
            normalized_name=name,
            matched_as="not_found",
        )

