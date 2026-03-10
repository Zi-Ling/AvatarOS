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
        image: str = "avatar-sandbox:latest",  # 预装常用包的沙箱镜像，见 server/Dockerfile.sandbox
        timeout: int = 30,
        mem_limit: str = "256m",
        cpu_quota: int = 50000,
        use_pool: bool = True,  # 是否使用容器池
        pool_size: int = 4,  # 容器池大小（增加到 4）
        network_mode: str = "none",  # 默认无网络；browser sandbox 传 "bridge"
    ):
        super().__init__()
        self.strategy = ExecutionStrategy.KATA
        self.image = image
        self.timeout = timeout
        self.mem_limit = mem_limit
        self.cpu_quota = cpu_quota
        self.use_pool = use_pool
        self.pool_size = pool_size
        self.network_mode = network_mode
        self._docker_client = None
        self._available = False
        self._is_podman = False  # 初始化时检测一次，缓存结果
        self._last_container_id = None
        self._pool = None

        self._check_availability()
    
    def _check_availability(self):
        """检查 Kata Runtime 是否可用（Podman 环境下直接跳过）"""
        try:
            import docker
            from .container_pool import is_podman
            client = docker.from_env()
            self._is_podman = is_podman(client)

            if self._is_podman:
                logger.info("[KataExecutor] Podman detected, KataExecutor disabled (use DockerExecutor)")
                return

            info = client.info()
            runtimes = info.get('Runtimes', {})

            if 'kata' in runtimes or 'kata-runtime' in runtimes:
                self._docker_client = client
                self._available = True
                logger.info("[KataExecutor] Kata Runtime is available")

                if self.use_pool:
                    from .container_pool import ContainerPool
                    self._pool = ContainerPool(
                        client=self._docker_client,
                        image=self.image,
                        runtime="kata",
                        pool_size=self.pool_size,
                        mem_limit=self.mem_limit,
                        cpu_quota=self.cpu_quota,
                    )
                    self._pool.start()
                    logger.info(f"[KataExecutor] Container pool started (size={self.pool_size})")
            else:
                logger.warning(
                    "[KataExecutor] Kata Runtime not configured in Docker. "
                    "See: https://github.com/kata-containers/kata-containers/blob/main/docs/install/docker-installation.md"
                )

        except ImportError:
            logger.warning("[KataExecutor] Docker library is not installed")
        except Exception as e:
            logger.warning(f"[KataExecutor] Failed to check Kata availability: {e}")
    
    def supports(self, skill: Any) -> bool:
        if not self._available:
            return False
        
        try:
            return skill.spec.risk_level in [SkillRiskLevel.EXECUTE, SkillRiskLevel.SYSTEM]
        except Exception as e:
            logger.warning(f"[KataExecutor] Failed to get risk_level: {e}")
            return False
    
    async def execute(self, skill: Any, input_data: Any, context: Any) -> Any:
        if not self._available:
            raise RuntimeError("Kata Runtime is not available")
        
        code = input_data.code if hasattr(input_data, 'code') else input_data.get("code", "")
        if not code:
            raise ValueError("No code provided")
        
        logger.debug(f"[KataExecutor] Executing {skill.spec.name}")

        # 从 context 获取 workspace 挂载配置（如果有）
        workspace_volumes = None
        if hasattr(context, "extra") and context.extra.get("workspace") is not None:
            workspace_volumes = context.extra["workspace"].get_docker_volumes()
        elif hasattr(context, "workspace") and context.workspace is not None:
            workspace_volumes = context.workspace.get_docker_volumes()
        
        try:
            if self.use_pool and self._pool:
                return await self._execute_with_pool(code, workspace_volumes)
            return await self._execute_without_pool(code)
        except Exception as e:
            logger.error(f"[KataExecutor] Failed: {skill.spec.name}, error: {e}")
            raise
    
    async def _execute_with_pool(self, code: str, workspace_volumes: Optional[dict] = None) -> dict:
        """使用容器池执行，自动适配 Docker/Podman"""
        import asyncio
        import uuid
        from .container_pool import SandboxFailure, exec_run_in_container

        loop = asyncio.get_event_loop()
        container = await loop.run_in_executor(None, self._pool.acquire, self.timeout)

        exec_failed = False
        run_id = uuid.uuid4().hex[:12]
        workdir = f"/run/{run_id}"

        try:
            self._last_container_id = container.id

            # 1. 创建隔离工作目录 + /workspace/output（Planner 写文件的标准路径）
            await loop.run_in_executor(
                None,
                lambda: exec_run_in_container(
                    container,
                    cmd=["mkdir", "-p", workdir, "/workspace/output"],
                    workdir="/",
                    use_podman=self._is_podman,
                ),
            )

            # 2. 执行 Python 代码
            exit_code, output = await loop.run_in_executor(
                None,
                lambda: exec_run_in_container(
                    container,
                    cmd=["python", "-c", code],
                    workdir=workdir,
                    demux=True,
                    use_podman=self._is_podman,
                )
            )

            stdout = output[0].decode("utf-8") if output[0] else ""
            stderr = output[1].decode("utf-8") if output[1] else ""

            # 3. 把容器内产出文件复制到 host session workspace
            if workspace_volumes:
                host_workspace = next(iter(workspace_volumes.keys()))
                # workdir 下的文件
                self._copy_from_container(container, workdir, host_workspace)
                # /workspace/output 下的文件（Planner 写文件的标准路径）
                self._copy_from_container(container, "/workspace/output", host_workspace)

            # 4. 清理容器内 run 目录
            await loop.run_in_executor(
                None,
                lambda: exec_run_in_container(container, cmd=["rm", "-rf", workdir], workdir="/", use_podman=self._is_podman),
            )

            logger.debug(f"[KataExecutor] Success (run_id={run_id})")

            return {
                "success": exit_code == 0,
                "stdout": stdout,
                "stderr": stderr,
                "result": None,
                "output": stdout if exit_code == 0 else stderr,
            }

        except SandboxFailure:
            raise
        except Exception as e:
            exec_failed = True
            raise
        finally:
            await loop.run_in_executor(None, self._pool.release, container, exec_failed)

    def _copy_from_container(self, container, container_dir: str, host_dir: str) -> None:
        """把容器内目录的文件 docker cp 到宿主机目录（跳过空目录）"""
        import io
        import tarfile
        from pathlib import Path

        try:
            bits, stat = container.get_archive(container_dir)
            buf = io.BytesIO(b"".join(bits))
            with tarfile.open(fileobj=buf) as tar:
                members = [m for m in tar.getmembers() if m.isfile()]
                if not members:
                    return
                host_path = Path(host_dir)
                host_path.mkdir(parents=True, exist_ok=True)
                for member in members:
                    # 去掉 run_id 前缀目录，直接平铺到 host_dir
                    parts = Path(member.name).parts
                    filename = parts[-1] if len(parts) > 1 else member.name
                    f = tar.extractfile(member)
                    if f is None:
                        continue
                    dest = host_path / filename
                    dest.write_bytes(f.read())
                    logger.info(f"[KataExecutor] Copied {filename} → {dest}")
        except Exception as e:
            logger.warning(f"[KataExecutor] docker cp failed: {e}")
    
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
                network_mode=self.network_mode,  # 默认 none，browser sandbox 传 bridge
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
