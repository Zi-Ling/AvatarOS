# app/avatar/learning/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from ..memory.manager import MemoryManager  # 仅用于类型注释


@dataclass
class LearningExample:
    """
    一条“可供学习”的样本：

    - kind      : 样本类型，例如：
        - "task_finished" : 一次任务执行结果
        - "skill_event"   : 一次技能调用（成功/失败）
        - "custom"        : 自定义
    - input_data: 主要输入内容，可以是任意结构（通常是 dict）
    - target    : 期望输出 / 标签（如果有的话，没有可为 None）
    - metadata  : 额外上下文信息（task_id、user_id、时间等）
    """

    kind: str
    input_data: Any
    target: Any | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LearningResult:
    """学习过程的结果描述："""

    success: bool
    message: str = ""
    data: Optional[Dict[str, Any]] = None


@dataclass
class LearningContext:
    """
    学习时的上下文：
    - workspace: 可选工作目录（比如用来保存模型/缓存）
    - user_id  : 当前用户（如果有）
    - task_id  : 当前任务（如果有）
    - memory   : 可选 MemoryManager，方便 learner 把结果写入长期记忆
    - extra    : 其他杂项信息
    """

    workspace: Optional[Path] = None
    user_id: Optional[str] = None
    task_id: Optional[str] = None
    memory: Optional[MemoryManager] = None
    extra: Dict[str, Any] = field(default_factory=dict)


class LearningModule(ABC):
    """抽象的学习模块定义。"""

    name: str = ""
    description: str = ""

    @abstractmethod
    def learn(
        self,
        example: LearningExample,
        *,
        ctx: LearningContext,
    ) -> LearningResult:
        """
        对单个 LearningExample 进行学习 / 更新操作。
        """
        raise NotImplementedError
