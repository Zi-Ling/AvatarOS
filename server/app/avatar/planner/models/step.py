from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional


class StepStatus(Enum):
    """步骤状态"""
    PENDING = auto()
    RUNNING = auto()
    SUCCESS = auto()
    FAILED = auto()
    SKIPPED = auto()


@dataclass
class StepResult:
    """步骤执行结果"""
    success: bool
    output: Any = None
    error: Optional[str] = None


@dataclass
class Step:
    """
    一个"调用某个 skill"的原子步骤。
    """
    id: str
    order: int
    skill_name: str
    params: Dict[str, Any] = field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    result: Optional[StepResult] = None
    retry: int = 0
    max_retry: int = 0
    depends_on: List[str] = field(default_factory=list)
    description: Optional[str] = None

    def can_run(self, step_index: Dict[str, "Step"]) -> bool:
        """检查步骤是否可以运行（依赖是否满足）"""
        if self.status not in (StepStatus.PENDING, StepStatus.FAILED):
            return False
        for dep_id in self.depends_on:
            dep = step_index.get(dep_id)
            if not dep:
                return False
            if dep.status not in (StepStatus.SUCCESS, StepStatus.SKIPPED):
                return False
        return True

    def add_dependency(self, step_id: str) -> None:
        """添加依赖步骤"""
        if step_id not in self.depends_on:
            self.depends_on.append(step_id)
