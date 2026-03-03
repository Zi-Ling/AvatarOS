from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional
import uuid
import time

from .step import Step, StepStatus, StepResult


class TaskStatus(Enum):
    """任务状态"""
    PENDING = auto()
    RUNNING = auto()
    SUCCESS = auto()
    FAILED = auto()
    PARTIAL_SUCCESS = auto()


@dataclass
class Task:
    """
    一次用户请求 / 任务实例。
    由若干 Step 组成。
    """
    id: str
    goal: str
    steps: List[Step]
    intent_id: Optional[str]
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_step(self, step: Step) -> None:
        """添加步骤"""
        self.steps.append(step)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """
        面向"新建任务"的简化构造：
        - 不要求 status/result
        - 主要给 Intent 或手写 task 用
        """
        task_id = data.get("id") or str(uuid.uuid4())
        intent_id = data.get("intent_id")  # 从 data 中获取 intent_id
        
        # 如果 intent_id 不在顶层，尝试从 metadata 中获取
        if not intent_id:
            metadata = data.get("metadata", {})
            intent_id = metadata.get("intent_id")
        
        steps_data = data.get("steps", [])
        steps: List[Step] = []
        for i, s in enumerate(steps_data):
            step_id = s.get("id") or f"step_{i}"
            steps.append(
                Step(
                    id=step_id,
                    order=i,
                    skill_name=s["skill"],
                    params=s.get("params", {}),
                    max_retry=s.get("max_retry", 0),
                    depends_on=s.get("depends_on", []),
                )
            )
        return cls(
            id=task_id,
            goal=data.get("goal", ""),
            steps=steps,
            intent_id=intent_id,
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_persisted_dict(cls, data: Dict[str, Any]) -> "Task":
        """
        用于从持久化存储恢复 Task（包含状态和结果）。
        与 to_dict 对应。
        """
        task_id = data["id"]
        goal = data.get("goal", "")
        status_str = data.get("status", TaskStatus.PENDING.name)
        try:
            status = TaskStatus[status_str]
        except KeyError:
            status = TaskStatus.PENDING

        created_at = data.get("created_at", time.time())
        updated_at = data.get("updated_at", created_at)
        metadata = data.get("metadata", {})
        intent_id = data.get("intent_id")

        steps_data = data.get("steps", [])
        steps: List[Step] = []
        for s in steps_data:
            step_status_str = s.get("status", StepStatus.PENDING.name)
            try:
                step_status = StepStatus[step_status_str]
            except KeyError:
                step_status = StepStatus.PENDING

            result_data = s.get("result")
            if result_data is not None:
                result = StepResult(
                    success=result_data.get("success", False),
                    output=result_data.get("output"),
                    error=result_data.get("error"),
                )
            else:
                result = None

            steps.append(
                Step(
                    id=s["id"],
                    order=s.get("order", 0),
                    skill_name=s["skill"],
                    params=s.get("params", {}),
                    status=step_status,
                    result=result,
                    retry=s.get("retry", 0),
                    max_retry=s.get("max_retry", 0),
                    depends_on=s.get("depends_on", []),
                )
            )

        return cls(
            id=task_id,
            goal=goal,
            steps=steps,
            intent_id=intent_id,
            status=status,
            created_at=created_at,
            updated_at=updated_at,
            metadata=metadata,
        )

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "id": self.id,
            "goal": self.goal,
            "status": self.status.name,
            "steps": [
                {
                    "id": s.id,
                    "order": s.order,
                    "skill": s.skill_name,
                    "skill_name": s.skill_name,  # 添加 skill_name 字段以兼容前端
                    "description": s.description,  # 添加 description 字段
                    "params": s.params,
                    "status": s.status.name,
                    "result": {
                        "success": s.result.success,
                        "output": s.result.output,
                        "error": s.result.error,
                    } if s.result else None,
                    "retry": s.retry,
                    "max_retry": s.max_retry,
                    "depends_on": s.depends_on,
                }
                for s in self.steps
            ],
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "intent_id": self.intent_id,
        }
