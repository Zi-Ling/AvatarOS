# app/api/task/__init__.py
"""
Task 模块（包含 Task/Run/Step 执行记录 API）
"""
from fastapi import APIRouter
from .execution import router as execution_router
from .models import (
    TaskListResponse,
    TaskDetailResponse,
    TaskListItemResponse,
    RunResponse,
    StepResponse,
)

task_router = APIRouter(prefix="/api/tasks", tags=["tasks"])
task_router.include_router(execution_router)

__all__ = [
    "task_router",
    "TaskListResponse",
    "TaskDetailResponse", 
    "TaskListItemResponse",
    "RunResponse",
    "StepResponse",
]

