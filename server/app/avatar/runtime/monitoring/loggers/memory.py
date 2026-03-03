# app/avatar/runtime/monitoring/loggers/memory.py
"""
内存日志实现
"""
from __future__ import annotations

from typing import Dict, List, Optional, Any
import uuid

from ..models import StepLogRecord, TaskLog, StepStatus, TaskStatus


class InMemoryStepLogger:
    """
    一个简单的内存实现：
    - 所有日志都存放在内存 dict 里
    - 方便测试、调试以及在一次进程生命周期内查看执行记录
    """

    def __init__(self) -> None:
        # key: task_id, value: TaskLog
        self._tasks: Dict[str, TaskLog] = {}

    def on_task_start(self, task_id: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        # 如果 task 已存在，可能是重试 / 重新执行，这里简单覆盖
        self._tasks[task_id] = TaskLog(task_id=task_id)

    def on_step_start(self, task_id: str, step: Any) -> None:
        task_log = self._tasks.get(task_id)
        if task_log is None:
            # 如果没有 task_log，说明流程没按预期调用 on_task_start
            # 为了防御，可以自动补一个
            task_log = TaskLog(task_id=task_id)
            self._tasks[task_id] = task_log

        record = StepLogRecord(
            id=str(uuid.uuid4()),
            task_id=task_id,
            step_id=getattr(step, "id", ""),
            order=getattr(step, "order", 0),
            skill_name=getattr(step, "skill_name", ""),
            status=getattr(step, "status", StepStatus.PENDING),
            input_params=getattr(step, "params", {}) or {},
            retry_count=getattr(step, "retry", 0),
        )
        task_log.steps.append(record)

    def on_step_end(self, task_id: str, step: Any, result: Any) -> None:
        task_log = self._tasks.get(task_id)
        if task_log is None:
            # 理论上不该发生，直接忽略
            return

        # 简单策略：找到该 task 下最后一个相同 step_id 的记录
        step_id = getattr(step, "id", "")
        record: Optional[StepLogRecord] = None
        for r in reversed(task_log.steps):
            if r.step_id == step_id:
                record = r
                break

        if record is None:
            # 没有找到对应的 start 记录，就新建一个兜底
            record = StepLogRecord(
                id=str(uuid.uuid4()),
                task_id=task_id,
                step_id=step_id,
                order=getattr(step, "order", 0),
                skill_name=getattr(step, "skill_name", ""),
                status=StepStatus.PENDING,
                input_params=getattr(step, "params", {}) or {},
                retry_count=getattr(step, "retry", 0),
            )
            task_log.steps.append(record)

        status = getattr(step, "status", StepStatus.SUCCESS)
        error_msg = result.error if hasattr(result, "error") else None

        record.mark_finished(
            status=status,
            output=getattr(result, "output", None),
            error=error_msg,
            retry_count=getattr(step, "retry", record.retry_count),
        )

    def on_task_end(
        self,
        task_id: str,
        status: TaskStatus,
        error: Optional[str] = None,
    ) -> None:
        task_log = self._tasks.get(task_id)
        if task_log is None:
            task_log = TaskLog(task_id=task_id)
            self._tasks[task_id] = task_log
        task_log.mark_finished(status=status, error=error)

    def get_task_log(self, task_id: str) -> Optional[TaskLog]:
        return self._tasks.get(task_id)

    def get_all_task_logs(self) -> List[TaskLog]:
        # 返回一个拷贝，防止外部随意修改内部状态
        return list(self._tasks.values())

