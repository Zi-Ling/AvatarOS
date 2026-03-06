# app/avatar/runtime/executor/docker.py

"""
Docker 执行器

使用 Docker 容器执行 Skill（主要是 python.run）。
当前作为 EXECUTE 级别的兜底方案。
"""

import asyncio
import logging
import tempfile
import os
from typing import Any, Optional

from .base import SkillExecutor, ExecutionStrategy
from app.avatar.skills.base import SkillRiskLevel

logger = logging.getLogger(__name__)


class DockerExecutor(SkillExecutor):
    """
    Docker 执行器
    
    特点：
    - 容器级隔离
    - 成熟稳定
    - 跨平台支持
    - 当前作为兜底方案
    """
    
    def __init__(
        self,
        image: str = "python:3.13-slim",  # 使用本地已有的镜像
        mem_limit: str = "256m",
        cpu_quota: int = 50000,
        timeout: int = 30,
        use_pool: bool = True,  # 是否使用容器池
        pool_size: int = 4,  # 容器池大小（增加到 4）
    ):
        super().__init__()
        self.strategy = ExecutionStrategy.DOCKER
        self.image = image
        self.mem_limit = mem_limit
        self.cpu_quota = cpu_quota
        self.timeout = timeout
        self.use_pool = use_pool
        self.pool_size = pool_size
        self._client = None
        self._available = False  # 添加 _available 属性
        self._last_container_id = None  # 跟踪最后使用的容器 ID（用于内存监控）
        self._pool = None  # 容器池
        self._check_docker()
    
    def _check_docker(self):
        """检查 Docker 是否可用"""
        try:
            import docker
            self._client = docker.from_env()
            # 测试连接
            self._client.ping()
            # 确保镜像存在
            self._ensure_image()
            self._available = True  # 设置为 True
            self._healthy = True
            logger.info(f"[DockerExecutor] Docker is available, image: {self.image}")
            
            # 初始化容器池（如果启用）
            if self.use_pool:
                from .container_pool import ContainerPool
                self._pool = ContainerPool(
                    client=self._client,
                    image=self.image,
                    runtime=None,  # Docker 不使用特殊 runtime
                    pool_size=self.pool_size,
                    mem_limit=self.mem_limit,
                    cpu_quota=self.cpu_quota,
                )
                self._pool.start()
                logger.info(f"[DockerExecutor] Container pool started (size={self.pool_size})")
        except Exception as e:
            self._available = False  # 设置为 False
            self._healthy = False
            logger.warning(f"[DockerExecutor] Docker is not available: {e}")
    
    def _ensure_image(self):
        """确保 Docker 镜像存在"""
        if not self._client:
            return
        
        try:
            # 检查镜像是否存在
            self._client.images.get(self.image)
            logger.info(f"[DockerExecutor] Image {self.image} found locally")
        except Exception:
            # 镜像不存在，尝试拉取
            logger.info(f"[DockerExecutor] Image {self.image} not found locally, pulling...")
            try:
                self._client.images.pull(self.image)
                logger.info(f"[DockerExecutor] Image {self.image} pulled successfully")
            except Exception as e:
                logger.error(f"[DockerExecutor] Failed to pull image: {e}")
                logger.error(f"[DockerExecutor] Please pull the image manually: docker pull {self.image}")
                self._available = False  # 设置为 False
                self._healthy = False
    
    def supports(self, skill: Any) -> bool:
        """
        支持 EXECUTE 级别的 Skill
        
        当前主要支持 python.run
        """
        if not self._available:  # 使用 _available
            return False
        
        try:
            risk_level = skill.spec.meta.risk_level
            # 支持 EXECUTE 和 SYSTEM 级别
            if risk_level not in [SkillRiskLevel.EXECUTE, SkillRiskLevel.SYSTEM]:
                return False
            
            # 当前只支持 python.run
            api_name = skill.spec.api_name
            return api_name == "python.run"
            
        except Exception as e:
            logger.warning(f"[DockerExecutor] Failed to check support: {e}")
            return False
    
    async def execute(self, skill: Any, input_data: Any, context: Any) -> Any:
        """
        在 Docker 容器中执行 Skill
        
        Args:
            skill: Skill 实例
            input_data: 输入数据
            context: SkillContext
        
        Returns:
            执行结果（Skill 的输出模型）
        """
        if not self._available:  # 使用 _available
            raise RuntimeError("Docker is not available")
        
        api_name = skill.spec.api_name
        logger.debug(f"[DockerExecutor] Executing {api_name}")
        
        # 当前只支持 python.run
        if api_name != "python.run":
            raise ValueError(f"DockerExecutor only supports python.run, got {api_name}")
        
        # 获取代码
        code = input_data.code
        
        # 在容器中执行
        try:
            result_dict = await self._run_python_in_container(code)
            logger.debug(f"[DockerExecutor] Success: {api_name}")
            
            # 将字典转换为 Skill 的输出模型
            output_model = skill.spec.output_model
            return output_model(**result_dict)
            
        except Exception as e:
            logger.error(f"[DockerExecutor] Failed: {api_name}, error: {e}")
            # 返回失败的输出模型
            output_model = skill.spec.output_model
            return output_model(
                success=False,
                message=str(e),
                stdout="",
                stderr=str(e)
            )
    
    async def _run_python_in_container(self, code: str) -> dict:
        """
        在 Docker 容器中执行 Python 代码
        
        Args:
            code: Python 代码
        
        Returns:
            执行结果字典
        """
        import docker
        
        # 创建临时目录
        with tempfile.TemporaryDirectory() as tmpdir:
            # 写入代码文件
            code_file = os.path.join(tmpdir, "script.py")
            with open(code_file, "w", encoding="utf-8") as f:
                f.write(code)
            
            try:
                # 运行容器
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    self._run_container_sync,
                    tmpdir
                )
                return result
                
            except docker.errors.ContainerError as e:
                # 容器执行失败（非零退出码）
                return {
                    "success": False,
                    "message": f"Container execution failed: {str(e)}",
                    "stdout": e.stdout.decode("utf-8") if e.stdout else "",
                    "stderr": e.stderr.decode("utf-8") if e.stderr else str(e),
                    "result": None,
                    "variables": {},
                }
            except Exception as e:
                # 其他错误
                return {
                    "success": False,
                    "message": f"Docker execution error: {str(e)}",
                    "stdout": "",
                    "stderr": str(e),
                    "result": None,
                    "variables": {},
                }
    
    def _run_container_sync(self, tmpdir: str) -> dict:
        """
        同步运行容器（在线程池中执行）
        
        Args:
            tmpdir: 临时目录路径
        
        Returns:
            执行结果字典
        """
        # 如果启用容器池，使用池中的容器
        if self.use_pool and self._pool:
            return self._run_with_pool(tmpdir)
        
        # 否则，创建新容器
        return self._run_without_pool(tmpdir)
    
    def _run_with_pool(self, tmpdir: str) -> dict:
        """使用容器池执行"""
        container = self._pool.acquire(timeout=self.timeout)
        if not container:
            raise RuntimeError("Failed to acquire container from pool")
        
        try:
            # 保存容器 ID（用于内存监控）
            self._last_container_id = container.id
            
            # 读取代码文件
            code_file = os.path.join(tmpdir, "script.py")
            with open(code_file, "r", encoding="utf-8") as f:
                code = f.read()
            
            # 在容器中执行命令（直接传递代码）
            exit_code, output = container.exec_run(
                cmd=["python", "-c", code],
                demux=True,  # 分离 stdout 和 stderr
            )
            
            stdout = output[0].decode("utf-8") if output[0] else ""
            stderr = output[1].decode("utf-8") if output[1] else ""
            
            if exit_code == 0:
                return {
                    "success": True,
                    "message": "Execution completed",
                    "stdout": stdout,
                    "stderr": stderr,
                    "result": stdout.strip() if stdout.strip() else None,
                    "variables": {},
                }
            else:
                return {
                    "success": False,
                    "message": f"Container exited with code {exit_code}",
                    "stdout": stdout,
                    "stderr": stderr,
                    "result": None,
                    "variables": {},
                }
        
        finally:
            # 归还容器到池中
            self._pool.release(container)
    
    def _run_without_pool(self, tmpdir: str) -> dict:
        """不使用容器池执行（创建新容器）"""
        # 创建容器（不自动删除，以便获取 stats）
        container = self._client.containers.create(
            image=self.image,
            command=["python", "/workspace/script.py"],
            volumes={tmpdir: {"bind": "/workspace", "mode": "ro"}},
            mem_limit=self.mem_limit,
            cpu_quota=self.cpu_quota,
            network_mode="none",  # 禁用网络
            detach=True,
        )
        
        try:
            # 保存容器 ID（用于内存监控）
            self._last_container_id = container.id
            
            # 启动容器
            container.start()
            
            # 等待容器完成
            result = container.wait(timeout=self.timeout)
            
            # 获取输出
            stdout = container.logs(stdout=True, stderr=False).decode("utf-8")
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8")
            
            # 检查退出码
            exit_code = result.get("StatusCode", 0)
            
            if exit_code == 0:
                return {
                    "success": True,
                    "message": "Execution completed",
                    "stdout": stdout,
                    "stderr": stderr,
                    "result": stdout.strip() if stdout.strip() else None,
                    "variables": {},
                }
            else:
                return {
                    "success": False,
                    "message": f"Container exited with code {exit_code}",
                    "stdout": stdout,
                    "stderr": stderr,
                    "result": None,
                    "variables": {},
                }
        
        finally:
            # 清理容器
            try:
                container.remove(force=True)
            except Exception as e:
                logger.warning(f"[DockerExecutor] Failed to remove container: {e}")
    
    def cleanup(self):
        """清理 Docker 客户端和容器池"""
        # 关闭容器池
        if self._pool:
            self._pool.shutdown()
            self._pool = None
        
        # 关闭 Docker 客户端
        if self._client:
            self._client.close()
            self._client = None
