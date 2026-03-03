# app/avatar/runtime/monitoring/loggers/null.py
"""
空日志实现
"""
from __future__ import annotations

from typing import Optional, Any, Dict, List


class NullStepLogger:
    """
    一个什么都不干的实现，适合在你不想记录日志、但又想保留接口的时候使用
    """

    def on_task_start(self, task_id: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        return None

    def on_step_start(self, task_id: str, step: Any) -> None:
        return None

    def on_step_end(self, task_id: str, step: Any, result: Any) -> None:
        return None

    def on_task_end(
        self,
        task_id: str,
        status: Any,
        error: Optional[str] = None,
    ) -> None:
        return None

    def get_task_log(self, task_id: str) -> None:
        return None

    def get_all_task_logs(self) -> List:
        return []

