# app/avatar/memory/provider.py
from __future__ import annotations

from typing import Optional

from .manager import MemoryManager

# Global instance for dependency injection
_memory_manager_instance: Optional[MemoryManager] = None


def set_memory_manager(manager: MemoryManager) -> None:
    """Set the global MemoryManager instance"""
    global _memory_manager_instance
    _memory_manager_instance = manager


def get_memory_manager() -> MemoryManager:
    """
    FastAPI dependency to get the MemoryManager instance
    
    Usage:
        @router.get("/endpoint")
        async def endpoint(memory_manager: MemoryManager = Depends(get_memory_manager)):
            ...
    """
    if _memory_manager_instance is None:
        raise RuntimeError("MemoryManager not initialized. Call set_memory_manager() first.")
    return _memory_manager_instance


class MemoryProvider:
    """
    一个统一的 MemoryProvider：
    - 当前版本 (v0) 非常简单，只返回 None 或空字符串
    - 未来可以在这个类里添加：
        - 从 episodic 中查找最近相关任务
        - 从 knowledge 中做 RAG 检索
        - 从 state 中抓取工作变量
        - 按一定策略组合它们
    """

    def __init__(self, manager: MemoryManager):
        """
        MemoryManager 是你 memory 系统的核心入口，
        包含：
            episodic/
            knowledge/
            state/
        未来 MemoryProvider 可以根据需要调用 manager 内的组件。
        """
        self.manager = manager

    def get_relevant_memory(self, user_request: str) -> Optional[str]:
        """
        v0 版本：直接返回 None。
        明天跑 MVP 完全够用。

        未来可扩展逻辑示例（可按需加入）：
        1) episodic = self.manager.episodic.search(user_request)
        2) knowledge = self.manager.knowledge.search(user_request)
        3) state = self.manager.state.dump()

        然后组合：
            return f"{episodic}\n{knowledge}\n{state}"
        """
        return None
