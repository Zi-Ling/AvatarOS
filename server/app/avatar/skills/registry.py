# app/avatar/skills/registry.py

from __future__ import annotations

from typing import Dict, Type, List, Optional, Any, Iterator
import logging

from .base import BaseSkill, SkillSpec

logger = logging.getLogger(__name__)


class SkillRegistry:
    """
    Skill 注册表 - 唯一注册点

    存储 Type[BaseSkill]（类，不是实例）。
    支持按 name 或 alias 查找。
    """

    def __init__(self):
        self._skills: Dict[str, Type[BaseSkill]] = {}       # name -> class
        self._by_alias: Dict[str, str] = {}                  # alias -> name

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self, skill_cls: Type[BaseSkill]) -> None:
        if not hasattr(skill_cls, "spec") or not isinstance(skill_cls.spec, SkillSpec):
            raise ValueError(f"{skill_cls.__name__} must have a valid 'spec: SkillSpec'")

        spec = skill_cls.spec

        if spec.name in self._skills:
            raise ValueError(f"Skill already registered: {spec.name}")

        self._skills[spec.name] = skill_cls

        for alias in spec.aliases:
            if alias in self._by_alias:
                logger.warning(f"Duplicate alias '{alias}' for '{spec.name}', skipping")
                continue
            self._by_alias[alias] = spec.name

        logger.debug(f"Registered skill: {spec.name} (aliases={spec.aliases})")

    # ── Lookup ────────────────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[Type[BaseSkill]]:
        """按 name 或 alias 查找 skill 类，找不到返回 None。"""
        cls = self._skills.get(name)
        if cls:
            return cls
        canonical = self._by_alias.get(name)
        if canonical:
            return self._skills.get(canonical)
        return None

    def get_instance(self, name: str) -> BaseSkill:
        cls = self.get(name)
        if not cls:
            raise ValueError(f"Skill not found: {name}")
        return cls()

    def iter_skills(self) -> Iterator[Type[BaseSkill]]:
        return iter(self._skills.values())

    def list_specs(self) -> List[SkillSpec]:
        return [cls.spec for cls in self._skills.values()]

    # ── LLM Tool Schema ───────────────────────────────────────────────────────

    def to_tool_schemas(self) -> List[Dict[str, Any]]:
        """生成 LLM tool calling 格式的 schema 列表。"""
        schemas = []
        for cls in self._skills.values():
            spec = cls.spec
            schemas.append({
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.input_model.model_json_schema(),
            })
        return schemas

    def describe_skills(self) -> Dict[str, Any]:
        """返回所有 skill 的描述字典（供 prompt builder 使用）。"""
        result = {}
        for name, cls in self._skills.items():
            spec = cls.spec
            input_schema = spec.input_model.model_json_schema()
            result[name] = {
                "description": spec.description,
                "params_schema": input_schema.get("properties", {}),
                "required": input_schema.get("required", []),
                "side_effects": [e.value for e in spec.side_effects],
                "risk_level": spec.risk_level.value,
            }
        return result

    def describe_skills_simple(self) -> str:
        """轻量字符串格式，用于 prefix caching 优化。"""
        lines = []
        for name in sorted(self._skills):
            spec = self._skills[name].spec
            desc = spec.description.split("\n")[0]
            lines.append(f"- {name}: {desc}")
        return "\n".join(lines)

    # ── Tag-based classification queries ─────────────────────────────────
    # Centralized tag sets and classification methods.
    # All runtime code should use these instead of inline tag checks.

    ANSWER_TAGS = frozenset({"answer", "reply", "fallback", "回答", "回复"})
    SEARCH_TAGS = frozenset({"search", "搜索", "查找", "检索"})

    def has_tags(self, skill_name: str, tag_set: frozenset) -> bool:
        """Check if a skill's tags intersect with the given tag set."""
        cls = self.get(skill_name)
        if not cls:
            return False
        return bool(set(cls.spec.tags) & tag_set)

    def is_answer_skill(self, skill_name: str) -> bool:
        """Check if skill is a text answer/reply/fallback skill."""
        return self.has_tags(skill_name, self.ANSWER_TAGS)

    def is_search_skill(self, skill_name: str) -> bool:
        """Check if skill is a search/retrieval skill."""
        return self.has_tags(skill_name, self.SEARCH_TAGS)

    def is_fs_write_skill(self, skill_name: str) -> bool:
        """Check if skill is a file-writing skill (WRITE + FS side effect)."""
        from .base import SkillRiskLevel, SideEffect
        cls = self.get(skill_name)
        if not cls:
            return False
        spec = cls.spec
        return spec.risk_level == SkillRiskLevel.WRITE and SideEffect.FS in spec.side_effects

    def is_code_skill(self, skill_name: str) -> bool:
        """Check if skill is a code execution skill (risk_level == EXECUTE)."""
        from .base import SkillRiskLevel
        cls = self.get(skill_name)
        if not cls:
            return False
        return cls.spec.risk_level == SkillRiskLevel.EXECUTE

    def find_by_tags(self, tag_set: frozenset) -> Optional[Type[BaseSkill]]:
        """Find the first skill whose tags intersect with the given tag set."""
        for cls in self._skills.values():
            if set(cls.spec.tags) & tag_set:
                return cls
        return None

    # ── Skill Search (keyword-based, no embedding) ───────────────────────────

    def search_skills(self, query: str, limit: int = 15) -> Dict[str, Any]:
        """关键词匹配技能，返回描述字典。"""
        if not query or len(query.strip()) < 2:
            return self.describe_skills()
        query_lower = query.lower()
        matched = {
            name: desc
            for name, desc in self.describe_skills().items()
            if query_lower in name.lower() or query_lower in desc.get("description", "").lower()
        }
        return matched or self.describe_skills()

    def search_skills_with_scores(self, query: str, limit: int = 15) -> List[Dict[str, Any]]:
        """关键词匹配技能，返回带固定分数的列表（供 router 兼容使用）。"""
        all_names = list(self._skills.keys())
        if not query or len(query.strip()) < 2:
            return [{"name": n, "score": 0.8} for n in all_names[:limit]]
        query_lower = query.lower()
        results = []
        for name, cls in self._skills.items():
            spec = cls.spec
            if query_lower in name.lower() or query_lower in spec.description.lower():
                results.append({"name": name, "score": 0.9})
            else:
                results.append({"name": name, "score": 0.8})
        return results[:limit]


# ── Global singleton ──────────────────────────────────────────────────────────

skill_registry = SkillRegistry()


def register_skill(skill_cls: Type[BaseSkill]) -> Type[BaseSkill]:
    """装饰器：注册 skill 类到全局注册表。"""
    skill_registry.register(skill_cls)
    return skill_cls
