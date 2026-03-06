# app/avatar/skills/__init__.py

"""
Avatar Skill System Entry Point.
"""

from .base import BaseSkill, SkillSpec, SideEffect, SkillRiskLevel
from .schema import SkillInput, SkillOutput
from .registry import SkillRegistry, register_skill, skill_registry
from .context import SkillContext

# Trigger registration of built-in skills
from . import builtin  # noqa: F401

__all__ = [
    "BaseSkill",
    "SkillSpec",
    "SideEffect",
    "SkillRiskLevel",
    "SkillInput",
    "SkillOutput",
    "SkillContext",
    "SkillRegistry",
    "skill_registry",
    "register_skill",
]
