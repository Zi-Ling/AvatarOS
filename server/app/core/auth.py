# app/core/auth.py
"""
可选的 API Token 认证中间件

通过环境变量 API_TOKEN 启用。未设置时所有请求放行。
设置后，请求需携带 Authorization: Bearer <token> 头。

跳过的路径：
- / (根路径健康检查)
- /docs, /redoc, /openapi.json (API 文档)
- /socket.io (WebSocket 连接)
"""
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# 不需要认证的路径前缀
SKIP_PATHS = ("/docs", "/redoc", "/openapi.json", "/socket.io")


class OptionalTokenAuthMiddleware(BaseHTTPMiddleware):
    """可选的 Bearer Token 认证中间件"""

    def __init__(self, app, token: str = ""):
        super().__init__(app)
        self.token = token
        if token:
            logger.info("API Token 认证已启用")
        else:
            logger.debug("API_TOKEN 未设置，跳过认证")

    async def dispatch(self, request: Request, call_next):
        # 未配置 token 时放行所有请求
        if not self.token:
            return await call_next(request)

        # 跳过不需要认证的路径
        path = request.url.path
        if path == "/" or path.startswith(SKIP_PATHS):
            return await call_next(request)

        # 校验 Authorization 头
        auth_header = request.headers.get("Authorization", "")
        if auth_header == f"Bearer {self.token}":
            return await call_next(request)

        return JSONResponse(
            status_code=401,
            content={"error": "Unauthorized", "detail": "Invalid or missing API token"},
        )
