# avatar/artifact/__init__.py
"""
Artifact 系统模块

提供 Artifact 自动发现、管理和检索功能
"""

from .utils import infer_artifact_type, extract_artifact_metadata
from .resolver import resolve_artifact_references, format_artifact_for_display
from .search import get_artifact_searcher, ArtifactSearcher

__all__ = [
    "infer_artifact_type", 
    "extract_artifact_metadata",
    "resolve_artifact_references",
    "format_artifact_for_display",
    "get_artifact_searcher",
    "ArtifactSearcher"
]

