# app/avatar/runtime/monitoring/protocol.py
"""
日志接口协议
"""
from __future__ import annotations

from typing import Protocol, Optional, Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from .models import TaskLog
    from app.avatar.planner.models import Step, StepResult, TaskStatus


class StepLogger(Protocol):
    """
    runtime 执行层使用的日志接口
    AvatarMain / TaskRunner 只依赖这个协议，不依赖具体实现
    """

    def on_task_start(self, task_id: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """开始执行一个 task 时被调用"""
        ...

    def on_step_start(self, task_id: str, step: Step) -> None:
        """某个 step 即将执行时调用"""
        ...

    def on_step_end(self, task_id: str, step: Step, result: StepResult) -> None:
        """某个 step 执行结束（不论成功/失败）时调用"""
        ...

    def on_task_end(
        self,
        task_id: str,
        status: TaskStatus,
        error: Optional[str] = None,
    ) -> None:
        """Task 执行完毕时调用"""
        ...

    def get_task_log(self, task_id: str) -> Optional[TaskLog]:
        """获取某个 task 的完整日志"""
        ...

    def get_all_task_logs(self) -> List[TaskLog]:
        """获取当前 logger 中记录的所有任务日志"""
        ...

