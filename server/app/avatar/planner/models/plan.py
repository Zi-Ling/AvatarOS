from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .task import Task


@dataclass
class Plan:
    """
    planner 输出的“计划对象”，可以包含 1 个或多个 Task。
    目前简单起见只放一个主 Task。
    """
    task: Task

    @property
    def steps(self) -> List["Step"]:
        return self.task.steps
