# app/avatar/learning/builtin/notebook.py
from __future__ import annotations

from typing import List

from ..base import LearningContext, LearningExample, LearningModule, LearningResult


class InMemoryNotebook(LearningModule):
    """
    一个最简单的学习模块：
    - 把所有收到的 LearningExample 缓存在内存里
    - 方便调试学习链路 & 做集成测试
    """

    name = "in_memory_notebook"
    description = "Stores learning examples inside the process."

    def __init__(self) -> None:
        self._examples: List[LearningExample] = []

    @property
    def samples(self) -> List[LearningExample]:
        # 返回浅拷贝，避免外部直接修改内部列表
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
