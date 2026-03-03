"""
输出提取策略
"""
from .direct import DirectMatchStrategy
from .semantic import SemanticMatchStrategy
from .pattern import PatternMatchStrategy
from .schema import SchemaMatchStrategy

__all__ = [
    "DirectMatchStrategy",
    "SemanticMatchStrategy",
    "PatternMatchStrategy",
    "SchemaMatchStrategy",
]

