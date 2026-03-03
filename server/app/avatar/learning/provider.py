# app/avatar/learning/provider.py
from __future__ import annotations

from typing import Optional

from .manager import LearningManager

# Global instance for dependency injection
_learning_manager_instance: Optional[LearningManager] = None


def set_learning_manager(manager: LearningManager) -> None:
    """Set the global LearningManager instance"""
    global _learning_manager_instance
    _learning_manager_instance = manager


def get_learning_manager() -> LearningManager:
    """
    FastAPI dependency to get the LearningManager instance
    
    Usage:
        @router.get("/endpoint")
        async def endpoint(learning_manager: LearningManager = Depends(get_learning_manager)):
            ...
    """
    if _learning_manager_instance is None:
        raise RuntimeError("LearningManager not initialized. Call set_learning_manager() first.")
    return _learning_manager_instance

