# app/dependencies.py
from fastapi import Request
from app.avatar.memory import MemoryManager
from app.avatar.learning import LearningManager
from app.avatar.runtime.main import AvatarMain
from app.intent_router.router import AvatarRouter
from app.log import LogAggregator


def get_memory_manager(request: Request) -> MemoryManager:
    """获取全局 MemoryManager 实例"""
    return request.app.state.memory_manager


def get_learning_manager(request: Request) -> LearningManager:
    """获取全局 LearningManager 实例"""
    return request.app.state.learning_manager


def get_avatar_runtime(request: Request) -> AvatarMain:
    """获取全局 AvatarMain 实例"""
    return request.app.state.avatar_runtime


def get_avatar_router(request: Request) -> AvatarRouter:
    """获取全局 AvatarRouter 实例"""
    return request.app.state.avatar_router


def get_log_aggregator(request: Request) -> LogAggregator:
    """获取全局 LogAggregator 实例"""
    return request.app.state.log_aggregator

