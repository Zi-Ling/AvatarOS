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
        image: str = "avatar-sandbox:latest",  # 预装常用包的沙箱镜像，见 server/Dockerfile.sandbox
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
        if not self._available:
            return False
        
        try:
            risk_level = skill.spec.risk_level
            if risk_level not in [SkillRiskLevel.EXECUTE, SkillRiskLevel.SYSTEM]:
                return False
            return skill.spec.name == "python.run"
        except Exception as e:
            logger.warning(f"[DockerExecutor] Failed to check support: {e}")
            return False
    
    async def execute(self, skill: Any, input_data: Any, context: Any) -> Any:
        if not self._available:
            raise RuntimeError("Docker is not available")
        
        api_name = skill.spec.name
        logger.debug(f"[DockerExecutor] Executing {api_name}")
        
        if api_name != "python.run":
            raise ValueError(f"DockerExecutor only supports python.run, got {api_name}")
        
        code = input_data.code

        # 从 context 获取 workspace 挂载配置
        workspace_volumes = None
        if hasattr(context, "extra") and context.extra.get("workspace") is not None:
            workspace_volumes = context.extra["workspace"].get_docker_volumes()
        
        try:
            result_dict = await self._run_python_in_container(code, workspace_volumes)
            logger.debug(f"[DockerExecutor] Success: {api_name}")
            output_model = skill.spec.output_model
            return output_model(**result_dict)
        except Exception as e:
            logger.error(f"[DockerExecutor] Failed: {api_name}, error: {e}")
            output_model = skill.spec.output_model
            return output_model(
                success=False,
                message=str(e),
                stdout="",
                stderr=str(e)
            )
    
    async def _run_python_in_container(self, code: str, workspace_volumes: Optional[dict] = None) -> dict:
        """在 Docker 容器中执行 Python 代码"""
        import docker
        
        with tempfile.TemporaryDirectory() as tmpdir:
            code_file = os.path.join(tmpdir, "script.py")
            with open(code_file, "w", encoding="utf-8") as f:
                f.write(code)
            
            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    self._run_container_sync,
                    tmpdir,
                    workspace_volumes,
                )
                return result
            except docker.errors.ContainerError as e:
                return {
                    "success": False,
                    "message": f"Container execution failed: {str(e)}",
                    "stdout": e.stdout.decode("utf-8") if e.stdout else "",
                    "stderr": e.stderr.decode("utf-8") if e.stderr else str(e),
                    "result": None,
                    "output": "",
                    "variables": {},
                }
            except Exception as e:
                return {
                    "success": False,
                    "message": f"Docker execution error: {str(e)}",
                    "stdout": "",
                    "stderr": str(e),
                    "result": None,
                    "output": "",
                    "variables": {},
                }
    
    def _run_container_sync(self, tmpdir: str, workspace_volumes: Optional[dict] = None) -> dict:
        """同步运行容器（在线程池中执行）"""
        if self.use_pool and self._pool:
            return self._run_with_pool(tmpdir)
        return self._run_without_pool(tmpdir, workspace_volumes)
    
    def _run_with_pool(self, tmpdir: str) -> dict:
        """使用容器池执行，自动适配 Docker/Podman"""
        from .container_pool import exec_run_in_container

        container = self._pool.acquire(timeout=self.timeout)

        exec_failed = False
        try:
            self._last_container_id = container.id

            code_file = os.path.join(tmpdir, "script.py")
            with open(code_file, "r", encoding="utf-8") as f:
                code = f.read()

            exit_code, output = exec_run_in_container(
                container,
                cmd=["python", "-c", code],
                workdir="/",
                demux=True,
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
                    "output": stdout.strip() if stdout.strip() else "",
                    "variables": {},
                }
            else:
                return {
                    "success": False,
                    "message": f"Container exited with code {exit_code}",
                    "stdout": stdout,
                    "stderr": stderr,
                    "result": None,
                    "output": stderr,
                    "variables": {},
                }

        except Exception:
            exec_failed = True
            raise
        finally:
            self._pool.release(container, failed=exec_failed)
    
    def _run_without_pool(self, tmpdir: str, workspace_volumes: Optional[dict] = None) -> dict:
        """不使用容器池执行（创建新容器），支持 workspace 挂载"""
        # 基础 volumes：代码文件
        volumes = {tmpdir: {"bind": "/workspace", "mode": "ro"}}

        # 如果有 session workspace，覆盖挂载（rw，容器可写 /workspace/output）
        if workspace_volumes:
            volumes = workspace_volumes

        container = self._client.containers.create(
            image=self.image,
            command=["python", "/workspace/script.py"] if not workspace_volumes else ["python", "-c", open(os.path.join(tmpdir, "script.py")).read()],
            volumes=volumes,
            mem_limit=self.mem_limit,
            cpu_quota=self.cpu_quota,
            network_mode="none",
            detach=True,
        )
        
        try:
            self._last_container_id = container.id
            container.start()
            result = container.wait(timeout=self.timeout)
            stdout = container.logs(stdout=True, stderr=False).decode("utf-8")
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8")
            exit_code = result.get("StatusCode", 0)
            
            return {
                "success": exit_code == 0,
                "message": "Execution completed" if exit_code == 0 else f"Container exited with code {exit_code}",
                "stdout": stdout,
                "stderr": stderr,
                "result": stdout.strip() if stdout.strip() and exit_code == 0 else None,
                "output": stdout.strip() if exit_code == 0 else stderr,
                "variables": {},
            }
        finally:
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
