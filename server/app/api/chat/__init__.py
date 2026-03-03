# app/api/chat/__init__.py
"""
Chat 模块
"""
from fastapi import APIRouter
from .message import router as message_router
from .session import router as session_router
from .speech import router as speech_routes_router

# Chat 路由
chat_router = APIRouter(prefix="/api/chat", tags=["chat"])
chat_router.include_router(message_router)
chat_router.include_router(session_router, prefix="/sessions")

# Speech 路由（独立）
speech_router = APIRouter(prefix="/api/speech", tags=["speech"])
speech_router.include_router(speech_routes_router)

__all__ = ["chat_router", "speech_router"]

