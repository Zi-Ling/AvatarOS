# app/avatar/runtime/executor/process.py

"""
进程执行器

使用 Python multiprocessing 在子进程中执行 Skill。
适用于 READ/WRITE 级别的 Skill（文件操作、数据库操作）。
"""

import asyncio
import logging
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any

from .base import SkillExecutor, ExecutionStrategy
from app.avatar.skills.base import SkillRiskLevel

logger = logging.getLogger(__name__)


def _warmup_task():
    """模块级空任务，用于预热进程池（必须在模块级才能被 pickle 序列化）"""
    import time
    time.sleep(0.01)
    return "warmed"


class ProcessExecutor(SkillExecutor):
    """
    进程执行器
    
    特点：
    - 进程级隔离
    - 中等性能（~100ms）
    - 适合文件、数据库操作
    """
    
    def __init__(self, max_workers: int = 4, timeout: int = 30):
        super().__init__()
        self.strategy = ExecutionStrategy.PROCESS
        self.max_workers = max_workers
        self.timeout = timeout
        self._pool = None
        self._warmed_up = False  # 标记是否已预热
    
    def _ensure_pool(self):
        """确保进程池已创建"""
        if self._pool is None:
            self._pool = ProcessPoolExecutor(max_workers=self.max_workers)
            logger.info(f"[ProcessExecutor] Created process pool with {self.max_workers} workers")
    
    def warmup(self):
        """
        预热进程池
        
        在应用启动时调用，提前创建进程池并提交空任务，
        避免首次执行时的 5.5s 延迟。
        """
        if self._warmed_up:
            logger.debug("[ProcessExecutor] Already warmed up")
            return
        
        logger.info("[ProcessExecutor] Warming up process pool...")
        
        # 创建进程池
        self._ensure_pool()
        
        # 提交 max_workers 个任务，确保所有进程都启动
        futures = []
        for i in range(self.max_workers):
            future = self._pool.submit(_warmup_task)
            futures.append(future)
        
        # 等待所有任务完成
        for future in futures:
            try:
                future.result(timeout=5)
            except Exception as e:
                logger.warning(f"[ProcessExecutor] Warmup task failed: {e}")
        
        self._warmed_up = True
        logger.info(f"[ProcessExecutor] Warmup completed ({self.max_workers} workers ready)")
    
    def supports(self, skill: Any) -> bool:
        """支持 READ/WRITE 级别的 Skill"""
        try:
            return skill.spec.risk_level in [SkillRiskLevel.READ, SkillRiskLevel.WRITE]
        except Exception as e:
            logger.warning(f"[ProcessExecutor] Failed to get risk_level: {e}")
            return False
    
    @staticmethod
    def _run_in_process(skill: Any, input_data: Any, context: Any) -> Any:
        """
        在子进程中执行 Skill
        
        注意：这个方法会在子进程中运行
        由于 Skills 是异步的，我们需要在子进程中创建事件循环
        """
        # 在子进程中创建新的事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # 运行异步 Skill
            result = loop.run_until_complete(skill.run(context, input_data))
            return result
        finally:
            loop.close()
    
    async def execute(self, skill: Any, input_data: Any, context: Any) -> Any:
        """
        在子进程中执行 Skill
        
        Args:
            skill: Skill 实例
            input_data: 输入数据
            context: _SkillCaller 或 SkillContext
        
        Returns:
            执行结果
        """
        logger.debug(f"[ProcessExecutor] Executing {skill.spec.name}")
        
        self._ensure_pool()
        
        try:
            # 如果 context 是 _SkillCaller，转换为 SkillContext
            from app.avatar.skills.context import SkillContext
            if hasattr(context, 'call_skill'):  # _SkillCaller 有 call_skill 方法
                # 创建简化的 SkillContext（只包含可序列化的字段）
                skill_context = SkillContext(
                    base_path=context.base_path,
                    dry_run=context.dry_run,
                    # 不传递 memory_manager, learning_manager, execution_context
                )
            else:
                skill_context = context
            
            # 测试序列化（调试用）
            import pickle
            try:
                pickle.dumps(skill_context)
                logger.debug(f"[ProcessExecutor] Context serialization OK")
            except Exception as e:
                logger.error(f"[ProcessExecutor] Context serialization failed: {e}")
                logger.error(f"[ProcessExecutor] Context type: {type(skill_context)}")
                raise
            
            # 在子进程中执行
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                self._pool,
                self._run_in_process,
                skill,
                input_data,
                skill_context
            )
            
            logger.debug(f"[ProcessExecutor] Success: {skill.spec.name}")
            return result
            
        except FutureTimeoutError:
            logger.error(f"[ProcessExecutor] Timeout: {skill.spec.name}")
            raise TimeoutError(f"Skill execution timeout after {self.timeout}s")
        except Exception as e:
            logger.error(f"[ProcessExecutor] Failed: {skill.spec.name}, error: {e}")
            raise
    
    def cleanup(self):
        """清理进程池"""
        if self._pool:
            logger.info("[ProcessExecutor] Shutting down process pool")
            self._pool.shutdown(wait=True)
            self._pool = None
    
    def __del__(self):
        """析构时清理资源"""
        self.cleanup()
