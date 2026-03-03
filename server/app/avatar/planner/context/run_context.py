from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class StepRunRecord:
    step_id: str
    status: str
    output: Any = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RunContext:
    """
    执行阶段的上下文。
    - 保存每个 step 的输出
    - 提供跨 step 读取中间结果的能力
    - 提供 trace / logging 所需的信息
    """

    task_id: str
    step_results: Dict[str, StepRunRecord] = field(default_factory=dict)
    shared: Dict[str, Any] = field(default_factory=dict)  # 任意共享数据

    def set_result(self, record: StepRunRecord) -> None:
        self.step_results[record.step_id] = record

    def get_result(self, step_id: str) -> Optional[StepRunRecord]:
        return self.step_results.get(step_id)

    def get_output(self, step_id: str) -> Any:
        rec = self.get_result(step_id)
        return None if rec is None else rec.output

    def put_shared(self, key: str, value: Any) -> None:
        self.shared[key] = value

    def get_shared(self, key: str, default: Any = None) -> Any:
        return self.shared.get(key, default)
