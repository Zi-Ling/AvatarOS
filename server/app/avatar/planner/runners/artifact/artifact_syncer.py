"""
Artifact Syncer

Synchronizes artifacts to Session and triggers indexing.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ArtifactSyncer:
    """
    Artifact 同步器
    
    职责：
    - 将 TaskContext 中的 artifacts 同步到 Session
    - 触发向量索引
    """
    
    @staticmethod
    async def sync_and_index(task_ctx: Any, step_ctx: Any) -> None:
        """
        同步并索引 Artifacts
        
        Args:
            task_ctx: TaskContext
            step_ctx: StepContext
        """
        if not task_ctx or not hasattr(task_ctx, 'artifacts'):
            return
        
        artifacts_to_sync = task_ctx.artifacts.items
        if not artifacts_to_sync:
            return
        
        # 1. 同步到 Session
        await ArtifactSyncer._sync_to_session(task_ctx, artifacts_to_sync)
        
        # 2. 触发索引
        await ArtifactSyncer._trigger_indexing(artifacts_to_sync)
    
    @staticmethod
    async def _sync_to_session(task_ctx: Any, artifacts: list) -> None:
        """同步到 SessionContext"""
        try:
            memory_manager = task_ctx.get_attachment("memory_manager")
            session_id = task_ctx.identity.session_id
            
            if not memory_manager or not session_id:
                return
            
            session_data = memory_manager.get_session_context(session_id)
            if not session_data:
                logger.warning(f"Session {session_id} not found, artifacts not synced")
                return
            
            from app.avatar.runtime.core import SessionContext
            session_ctx = SessionContext.from_dict(session_data)
            
            # 添加新的 artifacts（避免重复）
            for artifact in artifacts:
                session_artifact = {
                    "id": artifact.id,
                    "type": artifact.type,
                    "uri": artifact.uri,
                    "meta": artifact.meta
                }
                
                # 检查是否已存在
                if not any(a.get("id") == artifact.id for a in session_ctx.artifacts):
                    session_ctx.add_artifact(session_artifact)
            
            # 保存回 MemoryManager
            memory_manager.save_session_context(session_ctx)
            logger.info(f"ArtifactSyncer: ✅ Synced {len(artifacts)} artifacts to Session: {session_id}")
            
        except Exception as e:
            logger.warning(f"ArtifactSyncer: Failed to sync artifacts to Session: {e}")
    
    @staticmethod
    async def _trigger_indexing(artifacts: list) -> None:
        """触发向量索引（异步，不阻塞）"""
        try:
            from app.avatar.runtime.artifact.search import get_artifact_searcher
            
            artifact_searcher = get_artifact_searcher()
            
            for artifact in artifacts:
                artifact_for_index = {
                    "id": artifact.id,
                    "type": artifact.type,
                    "uri": artifact.uri,
                    "meta": artifact.meta
                }
                
                # 异步索引（不等待）
                asyncio.create_task(
                    asyncio.to_thread(artifact_searcher.index_artifact, artifact_for_index)
                )
            
            # Removed verbose debug log - too noisy
            # logger.debug(f"ArtifactSyncer: Triggered indexing for {len(artifacts)} artifacts")
            
        except Exception as e:
            logger.warning(f"ArtifactSyncer: Failed to trigger artifact indexing: {e}")

