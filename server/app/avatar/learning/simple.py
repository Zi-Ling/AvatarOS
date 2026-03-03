# app/avatar/learning/simple.py
from __future__ import annotations

from typing import List

from .base import LearningContext, LearningExample, LearningModule, LearningResult


class InMemoryNotebook(LearningModule):
    """
    一个最简单的学习模块：
    - 只是在内存里把所有收到的 LearningExample 存起来
    - 适合作为集成测试 / 调试用 learner
    """

    name = "in_memory_notebook"
    description = "Stores learning examples inside the process."

    def __init__(self) -> None:
        self._examples: List[LearningExample] = []

    @property
    def samples(self) -> List[LearningExample]:
        # 返回一个拷贝，避免外部直接修改内部列表
        return list(self._examples)

    def learn(
        self,
        example: LearningExample,
        *,
        ctx: LearningContext,
    ) -> LearningResult:
        self._examples.append(example)
        return LearningResult(
            success=True,
            message="example_buffered",
            data={
                "count": len(self._examples),
                "last_kind": example.kind,
                "workspace": str(ctx.workspace) if ctx.workspace else None,
                "user_id": ctx.user_id,
                "task_id": ctx.task_id,
            },
        )
