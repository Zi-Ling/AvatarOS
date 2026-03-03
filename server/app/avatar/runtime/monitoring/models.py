# app/avatar/runtime/monitoring/models.py
"""
日志数据模型
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import time

# 按项目实际路径调整导入
try:
    from app.avatar.planner.models import StepStatus, TaskStatus
except ImportError:
    # 避免还没移动文件时直接报错
    class StepStatus:  # type: ignore
        PENDING = "PENDING"
        RUNNING = "RUNNING"
        SUCCESS = "SUCCESS"
        FAILED = "FAILED"
        SKIPPED = "SKIPPED"

    class TaskStatus:  # type: ignore
        PENDING = "PENDING"
        RUNNING = "RUNNING"
        SUCCESS = "SUCCESS"
        FAILED = "FAILED"
        PARTIAL_SUCCESS = "PARTIAL_SUCCESS"


@dataclass
class StepLogRecord:
    """
    记录某一个 Step 的执行轨迹
    注意：这是 runtime 内部的日志结构，不是数据库 ORM
    """
    id: str
    task_id: str
    step_id: str
    order: int
    skill_name: str
    status: StepStatus

    input_params: Dict[str, Any] = field(default_factory=dict)
    output: Any = None
    error: Optional[str] = None

    retry_count: int = 0

    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    def mark_finished(
        self,
        status: StepStatus,
        output: Any = None,
        error: Optional[str] = None,
        retry_count: Optional[int] = None,
    ) -> None:
        self.finished_at = time.time()
        self.status = status
        self.output = output
        self.error = error
        if retry_count is not None:
            self.retry_count = retry_count

    @property
    def duration_ms(self) -> Optional[float]:
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at) * 1000.0


@dataclass
class TaskLog:
    """
    记录整个 Task 的执行情况以及其包含的所有 StepLogRecord
    """
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    error: Optional[str] = None

    steps: List[StepLogRecord] = field(default_factory=list)

    def mark_finished(self, status: TaskStatus, error: Optional[str] = None) -> None:
        self.finished_at = time.time()
        self.status = status
        self.error = error

    @property
    def duration_ms(self) -> Optional[float]:
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at) * 1000.0

