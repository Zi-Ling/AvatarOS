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
from .workspace import router as workspace_router

__all__ = [
    "chat_router",
    "task_router",
    "speech_router",
    "skill_router",
    "filesystem_router",
    "schedule_router",
    "history_router",
    "workspace_router",
]
