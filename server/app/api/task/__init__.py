# app/api/task/__init__.py
"""
Task 模块（包含 Task/Run/Step 执行记录 API）
"""
from fastapi import APIRouter
from .task import router as task_routes_router
from .execution import router as execution_router
from .models import (
    TaskListResponse,
    TaskDetailResponse,
    TaskListItemResponse,
    RunResponse,
    StepResponse,
)

# 合并成一个 task_router
task_router = APIRouter(prefix="/api/tasks", tags=["tasks"])
task_router.include_router(task_routes_router)  # 旧版 task API
task_router.include_router(execution_router)  # 新版 execution API

__all__ = [
    "task_router",
    "TaskListResponse",
    "TaskDetailResponse", 
    "TaskListItemResponse",
    "RunResponse",
    "StepResponse",
]

