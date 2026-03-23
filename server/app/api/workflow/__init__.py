"""
工作流编排 API 模块。

聚合 templates / instances / triggers 子路由。
"""
from fastapi import APIRouter

from .templates import router as templates_router
from .instances import router as instances_router
from .triggers import router as triggers_router

orchestration_router = APIRouter()
orchestration_router.include_router(templates_router)
orchestration_router.include_router(instances_router)
orchestration_router.include_router(triggers_router)

__all__ = ["orchestration_router"]
