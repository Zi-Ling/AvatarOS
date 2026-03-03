# app/avatar/learning/__init__.py
from .base import (
    LearningExample,
    LearningResult,
    LearningContext,
    LearningModule,
)
from .manager import LearningManager, LearningManagerConfig

from .builtin.notebook import InMemoryNotebook
from .skills.skill_stats import SkillStatsLearner
from .prefs.user_preference import UserPreferenceLearner

__all__ = [
    "LearningExample",
    "LearningResult",
    "LearningContext",
    "LearningModule",
    "LearningManager",
    "LearningManagerConfig",
    "InMemoryNotebook",
    "SkillStatsLearner",
    "UserPreferenceLearner",
]
