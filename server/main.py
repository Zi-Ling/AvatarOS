import sys
import asyncio
import os
import warnings
from pathlib import Path

# 抑制第三方库 (ctranslate2) 的 pkg_resources 废弃警告
warnings.filterwarnings("ignore", message="pkg_resources is deprecated", category=UserWarning)

# Fix for Windows Asyncio Subprocess (Playwright support)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import socketio

# 配置日志系统（在导入其他模块之前）
from app.core.logging_config import setup_logging
setup_logging(
    log_dir=Path("logs"),
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    enable_json=os.getenv("LOG_FORMAT", "text") == "json",
    enable_console=True,
)

from app.api import (
    chat_router, task_router, speech_router, skill_router,
    filesystem_router, schedule_router, history_router, workspace_router,
    state_router, memory_router, approval_router,
)
from app.api.learning import learning_router
from app.api.log import logging_router
from app.api.knowledge import router as knowledge_router
from app.api.workflow import router as workflow_router
from app.core.config import config
from app.io.manager import SocketManager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    from app.core.bootstrap import AppBootstrap
    bootstrap = AppBootstrap(app)
    await bootstrap.startup()
    yield
    await bootstrap.shutdown()


# 创建 FastAPI 实例
fastapi_app = FastAPI(
    title="IntelliAvatar API",
    description="智能虚拟助手后端服务",
    version="0.1.0",
    lifespan=lifespan,
)

# 配置 CORS
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局异常处理
@fastapi_app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error: {request.method} {request.url.path} - {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "内部服务器错误", "detail": str(exc)},
    )

# 注册路由
for router in [
    chat_router, task_router, speech_router, learning_router,
    logging_router, skill_router, filesystem_router, schedule_router,
    history_router, workspace_router, knowledge_router, workflow_router,
    state_router, memory_router, approval_router,
]:
    fastapi_app.include_router(router)


@fastapi_app.get("/")
async def root():
    return {"message": "IntelliAvatar API", "version": "0.1.0", "docs": "/docs"}


# Socket.IO 包装
socket_manager = SocketManager.get_instance()
app = socketio.ASGIApp(
    socket_manager.server,
    other_asgi_app=fastapi_app,
    socketio_path="socket.io",
)


if __name__ == "__main__":
    import uvicorn

    logger.info(f"🚀 启动 IntelliAvatar 后端服务 http://{config.server_host}:{config.server_port}")
    logger.info(f"🤖 LLM: {config.llm_model} | 📁 工作目录: {config.avatar_workspace}")

    uvicorn.run(
        "main:app",
        host=config.server_host,
        port=config.server_port,
        reload=False,
        log_level="info",
        access_log=False,
        loop="asyncio",
    )
