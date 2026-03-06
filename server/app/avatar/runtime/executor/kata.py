# app/avatar/runtime/executor/kata.py

"""
Kata Containers 执行器

使用 Kata Containers 提供轻量级 VM 隔离。
适用于 EXECUTE/SYSTEM 级别的完整功能任务。

特点：
- 硬件级隔离（基于 KVM）
- 完整 Python 环境
- 兼容 Docker 生态
- 生产级稳定（CNCF 毕业项目）

性能：
- 启动时间：~1s（首次），~500ms（热启动）
- 内存开销：~50MB
- 隔离级别：硬件级（VM）

实现方式：
- 方式 1：通过 Docker + Kata Runtime（推荐）
- 方式 2：直接使用 Kata CLI（更底层）
"""

import logging
from typing import Any, Optional

from .base import SkillExecutor, ExecutionStrategy
from app.avatar.skills.base import SkillRiskLevel

logger = logging.getLogger(__name__)


class KataExecutor(SkillExecutor):
    """
    Kata Containers 执行器
    
    特点：
    - 硬件级隔离（VM）
    - 完整 Python 环境
    - 兼容 Docker 生态
    - 生产级稳定
    """
    
    def __init__(
        self,
        image: str = "python:3.13-slim",  # 使用本地已有的镜像
        timeout: int = 30,
        mem_limit: str = "256m",
        cpu_quota: int = 50000,
        use_pool: bool = True,  # 是否使用容器池
        pool_size: int = 4,  # 容器池大小（增加到 4）
    ):
        super().__init__()
        self.strategy = ExecutionStrategy.KATA
        self.image = image
        self.timeout = timeout
        self.mem_limit = mem_limit
        self.cpu_quota = cpu_quota
        self.use_pool = use_pool
        self.pool_size = pool_size
        self._docker_client = None
        self._available = False
        self._last_container_id = None  # 跟踪最后使用的容器 ID（用于内存监控）
        self._pool = None  # 容器池
        
        # 检查 Kata Runtime 是否可用
        self._check_availability()
    
    def _check_availability(self):
        """检查 Kata Runtime 是否可用"""
        try:
            import docker
            client = docker.from_env()
            
            # 检查 Docker 是否配置了 Kata Runtime
            info = client.info()
            runtimes = info.get('Runtimes', {})
            
            if 'kata' in runtimes or 'kata-runtime' in runtimes:
                self._docker_client = client
                self._available = True
                logger.info("[KataExecutor] Kata Runtime is available")
                
                # 初始化容器池（如果启用）
                if self.use_pool:
                    from .container_pool import ContainerPool
                    self._pool = ContainerPool(
                        client=self._docker_client,
                        image=self.image,
                        runtime="kata",  # Kata Runtime
                        pool_size=self.pool_size,
                        mem_limit=self.mem_limit,
                        cpu_quota=self.cpu_quota,
                    )
                    self._pool.start()
                    logger.info(f"[KataExecutor] Container pool started (size={self.pool_size})")
            else:
                logger.warning(
                    "[KataExecutor] Kata Runtime is not configured in Docker. "
                    "Please configure Docker to use Kata Runtime. "
                    "See: https://github.com/kata-containers/kata-containers/blob/main/docs/install/docker-installation.md"
                )
                
        except ImportError:
            logger.warning("[KataExecutor] Docker library is not installed")
        except Exception as e:
            logger.warning(f"[KataExecutor] Failed to check Kata availability: {e}")
    
    def supports(self, skill: Any) -> bool:
        """
        支持 EXECUTE/SYSTEM 级别的 Skill
        
        检查逻辑：
        1. Kata Runtime 是否可用
        2. Skill 风险级别是否为 EXECUTE 或 SYSTEM
        """
        if not self._available:
            return False
        
        try:
            risk_level = skill.spec.meta.risk_level
            return risk_level in [SkillRiskLevel.EXECUTE, SkillRiskLevel.SYSTEM]
        except Exception as e:
            logger.warning(f"[KataExecutor] Failed to get risk_level: {e}")
            return False
    
    async def execute(self, skill: Any, input_data: Any, context: Any) -> Any:
        """
        在 Kata Container 中执行 Skill
        
        Args:
            skill: Skill 实例
            input_data: 输入数据（Pydantic 模型或字典，包含 code 字段）
            context: SkillContext
        
        Returns:
            执行结果
        """
        if not self._available:
            raise RuntimeError("Kata Runtime is not available")
        
        # 从 Pydantic 模型或字典获取代码
        code = input_data.code if hasattr(input_data, 'code') else input_data.get("code", "")
        if not code:
            raise ValueError("No code provided")
        
        logger.debug(f"[KataExecutor] Executing {skill.spec.api_name}")
        
        try:
            # 如果启用容器池，使用池中的容器
            if self.use_pool and self._pool:
                return await self._execute_with_pool(code)
            
            # 否则，创建新容器
            return await self._execute_without_pool(code)
            
        except Exception as e:
            logger.error(f"[KataExecutor] Failed: {skill.spec.api_name}, error: {e}")
            raise
    
    async def _execute_with_pool(self, code: str) -> dict:
        """使用容器池执行"""
        import asyncio
        
        loop = asyncio.get_event_loop()
        
        # 在线程池中获取容器
        container = await loop.run_in_executor(
            None,
            self._pool.acquire,
            self.timeout
        )
        
        if not container:
            raise RuntimeError("Failed to acquire container from pool")
        
        try:
            # 保存容器 ID（用于内存监控）
            self._last_container_id = container.id
            
            # 在容器中执行命令
            exit_code, output = await loop.run_in_executor(
                None,
                lambda: container.exec_run(
                    cmd=["python", "-c", code],
                    demux=True,  # 分离 stdout 和 stderr
                )
            )
            
            stdout = output[0].decode("utf-8") if output[0] else ""
            stderr = output[1].decode("utf-8") if output[1] else ""
            
            logger.debug(f"[KataExecutor] Success")
            
            if exit_code == 0:
                return {
                    "success": True,
                    "stdout": stdout,
                    "stderr": stderr,
                    "result": None
                }
            else:
                return {
                    "success": False,
                    "stdout": stdout,
                    "stderr": stderr,
                    "result": None
                }
        
        finally:
            # 归还容器到池中
            await loop.run_in_executor(None, self._pool.release, container)
    
    async def _execute_without_pool(self, code: str) -> dict:
        """不使用容器池执行（创建新容器）"""
        import asyncio
        
        loop = asyncio.get_event_loop()
        
        # 创建容器（不自动删除，以便获取 stats）
        container = await loop.run_in_executor(
            None,
            lambda: self._docker_client.containers.create(
                image=self.image,
                command=["python", "-c", code],
                runtime="kata",  # 使用 Kata Runtime
                mem_limit=self.mem_limit,
                cpu_quota=self.cpu_quota,
                network_mode="none",  # 禁用网络
                detach=True,
            )
        )
        
        try:
            # 保存容器 ID（用于内存监控）
            self._last_container_id = container.id
            
            # 启动容器
            await loop.run_in_executor(None, container.start)
            
            # 等待容器完成
            result = await loop.run_in_executor(
                None,
                lambda: container.wait(timeout=self.timeout)
            )
            
            # 获取输出
            stdout = await loop.run_in_executor(
                None,
                lambda: container.logs(stdout=True, stderr=False).decode("utf-8")
            )
            stderr = await loop.run_in_executor(
                None,
                lambda: container.logs(stdout=False, stderr=True).decode("utf-8")
            )
            
            # 检查退出码
            exit_code = result.get("StatusCode", 0)
            
            logger.debug(f"[KataExecutor] Success")
            
            # 返回结果（与 python.run 兼容）
            if exit_code == 0:
                return {
                    "success": True,
                    "stdout": stdout,
                    "stderr": stderr,
                    "result": None
                }
            else:
                return {
                    "success": False,
                    "stdout": stdout,
                    "stderr": stderr,
                    "result": None
                }
        
        finally:
            # 清理容器
            try:
                await loop.run_in_executor(None, lambda: container.remove(force=True))
            except Exception as e:
                logger.warning(f"[KataExecutor] Failed to remove container: {e}")
    
    def cleanup(self):
        """清理 Docker 客户端和容器池"""
        # 关闭容器池
        if self._pool:
            self._pool.shutdown()
            self._pool = None
        
        # 关闭 Docker 客户端
        if self._docker_client:
            logger.info("[KataExecutor] Closing Docker client")
            self._docker_client.close()
            self._docker_client = None
    
    def __del__(self):
        """析构时清理资源"""
        self.cleanup()
