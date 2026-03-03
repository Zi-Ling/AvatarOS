# app/api/task/models.py
"""
Task/Run/Step API 响应模型
"""
from pydantic import BaseModel


class TaskResponse(BaseModel):
    """任务基础响应"""
    id: str
    status: str
    result: dict | None = None
    error: str | None = None


class StepResponse(BaseModel):
    """步骤响应"""
    id: str
    step_index: int
    step_name: str
    skill_name: str
    status: str  # pending | running | completed | failed | skipped
    input_params: dict | None = None
    output_result: dict | None = None
    error_message: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None


class RunResponse(BaseModel):
    """运行响应"""
    id: str
    task_id: str
    status: str  # pending | running | completed | failed | cancelled
    summary: str | None = None
    error_message: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None
    steps: list[StepResponse] = []


class TaskDetailResponse(BaseModel):
    """任务详情响应"""
    id: str
    title: str
    intent_spec: dict
    task_mode: str  # one_shot | recurring
    created_at: str
    updated_at: str
    runs: list[RunResponse] = []


class TaskListItemResponse(BaseModel):
    """任务列表项响应"""
    id: str
    title: str
    task_mode: str
    created_at: str
    last_run_status: str | None = None
    run_count: int = 0


class TaskListResponse(BaseModel):
    """任务列表响应"""
    tasks: list[TaskListItemResponse]
    total: int

