# app/api/__init__.py
"""
API 模块 — 按前端模块分层导出所有路由

chat/    — 对话、语音
task/    — 任务执行
skill/   — 技能注册
workbench/ — Workbench 面板（trace, cost, approval, history, policy）
workspace/ — Workspace 模块（filesystem, artifacts, workspace）
knowledge/ — Knowledge 模块（memory, state, knowledge, learning）
setting/   — Setting 模块（settings, maintenance, schedule, workflow）
log/     — 日志
"""
from .chat import chat_router, speech_router
from .task import task_router
from .skill import router as skill_router

from .workbench import (
    trace_router,
    cost_router,
    approval_router,
    history_router,
    policy_router,
)
from .workspace import (
    workspace_router,
    filesystem_router,
    artifacts_router,
)
from .knowledge import (
    memory_router,
    state_router,
    knowledge_router,
    learning_router,
    semantic_router,
)
from .setting import (
    settings_router,
    maintenance_router,
    schedule_router,
)

__all__ = [
    # chat
    "chat_router",
    "speech_router",
    # task
    "task_router",
    # skill
    "skill_router",
    # workbench
    "trace_router",
    "cost_router",
    "approval_router",
    "history_router",
    "policy_router",
    # workspace
    "workspace_router",
    "filesystem_router",
    "artifacts_router",
    # knowledge
    "memory_router",
    "state_router",
    "knowledge_router",
    "learning_router",
    "semantic_router",
    # setting
    "settings_router",
    "maintenance_router",
    "schedule_router",
]
