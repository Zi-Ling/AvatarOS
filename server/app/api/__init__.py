# app/api/__init__.py
"""
API 模块 — 统一导出所有路由
"""
from .chat import chat_router, speech_router
from .task import task_router
from .skill import router as skill_router
from .filesystem import router as filesystem_router
from .schedule import router as schedule_router
from .history import router as history_router
from .artifacts import router as artifacts_router
from .workspace import router as workspace_router
from .state import router as state_router
from .memory import router as memory_router
from .approval import router as approval_router

__all__ = [
    "chat_router",
    "task_router",
    "speech_router",
    "skill_router",
    "filesystem_router",
    "schedule_router",
    "history_router",
    "artifacts_router",
    "workspace_router",
    "state_router",
    "memory_router",
    "approval_router",
]
