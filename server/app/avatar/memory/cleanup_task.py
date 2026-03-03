# avatar/memory/cleanup_task.py
"""
Memory Cleanup Background Task

定期清理旧的 Episodic Memory，防止数据库膨胀
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from .manager import MemoryManager

import logging

logger = logging.getLogger(__name__)


class MemoryCleanupTask:
    """
    后台清理任务：定期清理旧的记忆
    
    使用方式：
        cleanup = MemoryCleanupTask(memory_manager, interval_hours=24)
        await cleanup.start()
    """
    
    def __init__(
        self,
        memory_manager: MemoryManager,
        interval_hours: int = 24,  # 每 24 小时清理一次
        days_to_keep: int = 30,    # 保留最近 30 天
        keep_successful_tasks: bool = True,  # 永久保留成功任务
        cleanup_artifacts: bool = True,  # 是否清理 Artifacts
        artifact_rules: Optional[dict] = None,  # Artifact 清理规则
    ) -> None:
        self.memory_manager = memory_manager
        self.interval_hours = interval_hours
        self.days_to_keep = days_to_keep
        self.keep_successful_tasks = keep_successful_tasks
        self.cleanup_artifacts = cleanup_artifacts
        
        # 默认 Artifact 清理规则
        self.artifact_rules = artifact_rules or {
            "default": {
                "idle_duration": 86400,      # 24 小时后归档
                "archive_duration": 604800,  # 7 天后删除
            },
            "by_type": {
                "document": {
                    "archive_duration": 2592000,  # 30 天（文档保留更久）
                },
                "image": {
                    "archive_duration": 1209600,  # 14 天
                },
            }
        }
        
        self._task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self) -> None:
        """启动后台清理任务"""
        if self._running:
            logger.warning("Cleanup task already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"Memory cleanup task started (interval: {self.interval_hours}h, keep: {self.days_to_keep}d)")
    
    async def stop(self) -> None:
        """停止后台清理任务"""
        if not self._running:
            return
        
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Memory cleanup task stopped")
    
    async def _run_loop(self) -> None:
        """清理循环"""
        while self._running:
            try:
                # 执行一次清理
                await self._do_cleanup()
                
                # 等待下一次清理
                await asyncio.sleep(self.interval_hours * 3600)
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Memory cleanup error: {e}")
                # 发生错误后等待 1 小时再重试
                await asyncio.sleep(3600)
    
    async def _do_cleanup(self) -> None:
        """执行清理"""
        logger.info(f"Running memory cleanup at {datetime.utcnow().isoformat()}")
        
        try:
            # 1. 清理旧记忆
            stats = await asyncio.to_thread(
                self.memory_manager.cleanup_old_memories,
                days_to_keep=self.days_to_keep,
                keep_successful_tasks=self.keep_successful_tasks,
            )
            
            logger.info(f"Memory cleanup completed: {stats}")
            
            # 2. 清理 Artifacts（如果启用）
            if self.cleanup_artifacts:
                artifact_stats = await asyncio.to_thread(
                    self._cleanup_artifacts
                )
                logger.info(f"Artifact cleanup completed: {artifact_stats}")
        
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
    
    def cleanup_now(self) -> dict:
        """立即执行一次清理（同步版本，供手动调用）"""
        stats = self.memory_manager.cleanup_old_memories(
            days_to_keep=self.days_to_keep,
            keep_successful_tasks=self.keep_successful_tasks,
        )
        
        if self.cleanup_artifacts:
            artifact_stats = self._cleanup_artifacts()
            stats["artifacts"] = artifact_stats
        
        return stats
    
    def _cleanup_artifacts(self) -> dict:
        """
        清理 Artifacts
        
        策略：
        1. 扫描所有 Session 的 artifacts
        2. 根据规则判断是否需要删除
        3. 删除过期的 artifacts
        """
        import time
        import os
        
        stats = {
            "scanned": 0,
            "deleted": 0,
            "archived": 0,
            "errors": 0,
            "space_freed": 0  # 字节
        }
        
        try:
            # 获取所有 working state keys
            # 注意：这里需要 MemoryManager 支持列出所有 session
            # 简化实现：只处理能找到的 sessions
            
            # 遍历所有 session artifacts
            # 这是一个简化的实现，实际可能需要更复杂的遍历逻辑
            
            # 由于 MemoryManager 的 working_state 存储在 SQLite 中
            # 我们需要通过数据库查询来遍历所有 session
            
            # 简化版本：只打印日志，实际删除需要更完善的实现
            logger.debug("[ArtifactCleanup] Artifact cleanup is not fully implemented yet")
            
        except Exception as e:
            logger.error(f"[ArtifactCleanup] Error: {e}")
            stats["errors"] += 1
        
        return stats

