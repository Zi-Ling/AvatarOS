"""
结构化数据层 — 入口模块

提供 get_data_service() 懒初始化单例，与现有 get_state_service / get_memory_service 模式一致。
注意：DataService.initialize() 是异步的，首次使用前需调用 await ensure_initialized()。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .service import DataService

logger = logging.getLogger(__name__)

_data_service: Optional[DataService] = None
_initialized: bool = False
_init_lock = asyncio.Lock()


def get_data_service() -> DataService:
    """获取 DataService 单例（同步，与现有模式一致）"""
    global _data_service
    if _data_service is None:
        _data_service = _create_service()
    return _data_service


async def ensure_initialized() -> DataService:
    """确保 DataService 已完成异步初始化（建表、迁移等）"""
    global _initialized
    svc = get_data_service()
    if not _initialized:
        async with _init_lock:
            if not _initialized:
                await svc.initialize()
                _initialized = True
                logger.info("DataService 异步初始化完成")
    return svc


def _create_service() -> DataService:
    """创建 DataService 实例（内部使用）"""
    from app.core.config import config
    from .builtin_objects import register_builtin_objects
    from .proposal import ProposalService
    from .registry import ObjectRegistry
    from .storage import SQLiteBackend

    backend = SQLiteBackend(config.data_db_path)
    registry = ObjectRegistry()
    register_builtin_objects(registry)

    proposal_svc = ProposalService(
        registry=registry,
        record_storage=backend,
        workflow_storage=backend,
        schema_storage=backend,
    )

    return DataService(
        registry=registry,
        record_storage=backend,
        proposal_service=proposal_svc,
        schema_storage=backend,
        workflow_storage=backend,
    )
