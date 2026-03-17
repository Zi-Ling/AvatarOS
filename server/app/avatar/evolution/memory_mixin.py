"""
memory_mixin.py — MemoryManagerEvolutionMixin

MemoryManager 的演化扩展。
阶段二仅实现注入硬限制和反思结果隔离，不实现 stable_heuristic 写入。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.avatar.evolution.config import EvolutionConfig

logger = logging.getLogger(__name__)


class MemoryManagerEvolutionMixin:
    """
    MemoryManager 的演化扩展。
    与现有 MemoryManager 集成，扩展而非替换。
    阶段二仅实现注入硬限制和反思结果隔离。
    """

    def __init__(
        self,
        memory_manager: Any,
        config: Optional[EvolutionConfig] = None,
    ) -> None:
        self._memory_manager = memory_manager
        self._config = config or EvolutionConfig()

    def inject_memories_for_planner(
        self,
        task_type: str,
        goal: str,
        max_count: Optional[int] = None,
        max_total_length: Optional[int] = None,
    ) -> List[dict]:
        """
        基于任务相似度检索相关记忆并注入 Planner 上下文。
        严格遵守 max_count 和 max_total_length 硬限制。
        """
        max_count = max_count or self._config.max_memory_injection_count
        max_total_length = max_total_length or self._config.max_memory_injection_length

        # 从现有 MemoryManager 检索相似任务记忆
        memories: List[dict] = []
        try:
            results = self._memory_manager.search_similar_tasks(
                goal=goal,
                limit=max_count * 2,  # 多取一些，后面截断
            )
            memories = results if isinstance(results, list) else []
        except Exception as exc:
            logger.warning(f"[MemoryEvolutionMixin] search failed: {exc}")
            return []

        # 硬限制：最大条数
        memories = memories[:max_count]

        # 硬限制：最大总长度
        selected: List[dict] = []
        total_length = 0
        for mem in memories:
            mem_str = str(mem)
            if total_length + len(mem_str) > max_total_length:
                break
            selected.append(mem)
            total_length += len(mem_str)

        return selected

    def is_stable_heuristic_write_allowed(self) -> bool:
        """
        阶段二返回 False，阻止反思结果直接写入 stable_heuristic 层。
        阶段三+可根据 LearningCandidate 状态开放。
        """
        return False
