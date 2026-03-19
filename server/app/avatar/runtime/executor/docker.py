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

_OUTPUT_MARKER = "__OUTPUT__:"


def _extract_output_from_stdout(stdout: str):
    """
    从 stdout 中识别 __OUTPUT__:<json> 标记行，提取结构化输出。
    找到则返回解析后的 Python 对象；未找到则返回原始 stdout 字符串。
    多次调用 _output() 时取最后一次。
    """
    import json as _json
    result = stdout  # 默认退回字符串
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith(_OUTPUT_MARKER):
            payload = stripped[len(_OUTPUT_MARKER):]
            try:
                result = _json.loads(payload)
            except Exception:
                pass  # 解析失败则保持上一次结果
    return result


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
        network_mode: str = "none",  # 默认无网络；browser sandbox 传 "bridge"
    ):
        super().__init__()
        self.strategy = ExecutionStrategy.DOCKER
        self.image = image
        self.mem_limit = mem_limit
        self.cpu_quota = cpu_quota
        self.timeout = timeout
        self.use_pool = use_pool
        self.pool_size = pool_size
        self.network_mode = network_mode
        self._client = None
        self._available = False
        self._is_podman = False  # 初始化时检测一次，缓存结果
        self._last_container_id = None
        self._pool = None
        self._check_docker()
    
    def _check_docker(self):
        """检查 Docker/Podman 是否可用，并缓存 is_podman 结果"""
        try:
            import docker
            from .container_pool import is_podman
            self._client = docker.from_env()
            self._client.ping()
            self._is_podman = is_podman(self._client)
            if self._is_podman:
                logger.info("[DockerExecutor] Podman detected (Docker-compat mode)")
            self._ensure_image()
            self._available = True
            self._healthy = True
            logger.info(f"[DockerExecutor] Available, image={self.image}, podman={self._is_podman}")

            if self.use_pool:
                from .container_pool import ContainerPool
                self._pool = ContainerPool(
                    client=self._client,
                    image=self.image,
                    runtime=None,
                    pool_size=self.pool_size,
                    mem_limit=self.mem_limit,
                    cpu_quota=self.cpu_quota,
                    network_mode=self.network_mode,
                )
                self._pool.start()
                logger.info(f"[DockerExecutor] Container pool started (size={self.pool_size})")
        except Exception as e:
            self._available = False
            self._healthy = False
            logger.warning(f"[DockerExecutor] Not available: {e}")
    
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
        # Dual-mount 策略：
        #   session_root   → /session   (rw)  — 框架文件: input/, output/, logs/
        #   user_workspace → /workspace (rw)  — LLM 代码 cwd，文件直接落在用户目录
        # 当 user_workspace 不可用时，退回单挂载（session → /workspace）
        workspace_volumes = None
        base_path_str = None
        user_workspace_str = None
        if hasattr(context, "extra") and context.extra.get("workspace") is not None:
            _session_ws = context.extra["workspace"]
            # 尝试获取 user_workspace
            if hasattr(context, "base_path") and context.base_path is not None:
                _ubp = str(context.base_path.resolve()) if hasattr(context.base_path, "resolve") else str(context.base_path)
                user_workspace_str = _ubp
                # Dual-mount: session → /session, user_workspace → /workspace
                workspace_volumes = _session_ws.get_docker_volumes_dual(_ubp)
                base_path_str = str(_session_ws.output_dir)
                logger.debug(
                    f"[DockerExecutor] Dual-mount: session={_session_ws.root} → /session, "
                    f"user_workspace={_ubp} → /workspace"
                )
            else:
                # 无 user_workspace，退回单挂载
                workspace_volumes = _session_ws.get_docker_volumes()
                base_path_str = str(_session_ws.output_dir)
        elif hasattr(context, "base_path") and context.base_path is not None:
            # fallback：没有 SessionWorkspace 时，把 base_path 挂到容器 /workspace
            _bp = str(context.base_path.resolve()) if hasattr(context.base_path, "resolve") else str(context.base_path)
            workspace_volumes = {_bp: {"bind": "/workspace", "mode": "rw"}}
            base_path_str = _bp
            logger.debug(f"[DockerExecutor] No SessionWorkspace, fallback mount base_path={_bp} → /workspace")
        
        try:
            result_dict = await self._run_python_in_container(
                code, workspace_volumes,
                base_path=base_path_str,
                user_workspace=user_workspace_str,
            )
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
    
    async def _run_python_in_container(self, code: str, workspace_volumes: Optional[dict] = None, base_path: Optional[str] = None, user_workspace: Optional[str] = None) -> dict:
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
                    base_path,
                    user_workspace,
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
    
    def _run_container_sync(self, tmpdir: str, workspace_volumes: Optional[dict] = None, base_path: Optional[str] = None, user_workspace: Optional[str] = None) -> dict:
        """同步运行容器（在线程池中执行）"""
        if self.use_pool and self._pool:
            return self._run_with_pool(tmpdir, workspace_volumes=workspace_volumes, base_path=base_path, user_workspace=user_workspace)
        return self._run_without_pool(tmpdir, workspace_volumes, base_path=base_path, user_workspace=user_workspace)
    
    def _run_with_pool(self, tmpdir: str, workspace_volumes: Optional[dict] = None, base_path: Optional[str] = None, user_workspace: Optional[str] = None) -> dict:
        """使用容器池执行，通过 docker cp 传输文件（不依赖 volume mount）"""
        import tarfile, io
        from .container_pool import exec_run_in_container

        container = self._pool.acquire(timeout=self.timeout)

        exec_failed = False
        try:
            self._last_container_id = container.id

            code_file = os.path.join(tmpdir, "script.py")
            with open(code_file, "r", encoding="utf-8") as f:
                code = f.read()

            # 确保 /workspace 目录存在
            exec_run_in_container(
                container,
                cmd=["mkdir", "-p", "/workspace"],
                workdir="/",
                demux=False,
                use_podman=self._is_podman,
            )

            # 如果有 workspace_volumes，把宿主机文件 put_archive 到容器内
            # workspace_volumes 格式: {host_path: {"bind": container_path, "mode": "rw"}}
            if workspace_volumes:
                for host_path, mount_cfg in workspace_volumes.items():
                    container_path = mount_cfg["bind"]
                    if not os.path.exists(host_path):
                        continue
                    exec_run_in_container(
                        container,
                        cmd=["mkdir", "-p", container_path],
                        workdir="/",
                        demux=False,
                        use_podman=self._is_podman,
                    )
                    # 把 host_path 目录内容打包上传到容器
                    if os.path.isdir(host_path):
                        tar_buf = io.BytesIO()
                        with tarfile.open(fileobj=tar_buf, mode="w") as tar:
                            for item in os.listdir(host_path):
                                full = os.path.join(host_path, item)
                                tar.add(full, arcname=item)
                        tar_buf.seek(0)
                        container.put_archive(container_path, tar_buf)

            exit_code, output = exec_run_in_container(
                container,
                cmd=["python", "-c", code],
                workdir="/workspace",
                demux=True,
                use_podman=self._is_podman,
            )

            stdout = output[0].decode("utf-8") if output[0] else ""
            stderr = output[1].decode("utf-8") if output[1] else ""

            # 执行完成后，把容器 /workspace 下的新文件复制回宿主机
            if workspace_volumes and user_workspace and os.path.isdir(user_workspace):
                try:
                    bits, _ = container.get_archive("/workspace/.")
                    tar_bytes = b"".join(bits)
                    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tar:
                        for member in tar.getmembers():
                            # 跳过目录本身
                            if member.isdir():
                                continue
                            # 去掉 tar 内的前缀 "./"
                            member.name = member.name.lstrip("./")
                            if not member.name:
                                continue
                            tar.extract(member, path=user_workspace)
                except Exception as cp_err:
                    logger.debug(f"[DockerExecutor] Pool copy-back from /workspace: {cp_err}")

            if exit_code == 0:
                structured_output = _extract_output_from_stdout(stdout)
                _file_path = None
                if isinstance(structured_output, dict) and "__file__" in structured_output:
                    container_file_path = structured_output["__file__"]
                    _file_path = container_file_path

                    if base_path:
                        try:
                            bits, _ = container.get_archive(container_file_path)
                            tar_bytes = b"".join(bits)
                            with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tar:
                                for member in tar.getmembers():
                                    member.name = os.path.basename(member.name)
                                    tar.extract(member, path=base_path)
                            host_file = os.path.join(base_path, os.path.basename(container_file_path))
                            _file_path = host_file
                            logger.info(f"[DockerExecutor] Copied container file {container_file_path} → {host_file}")
                        except Exception as cp_err:
                            logger.warning(f"[DockerExecutor] Failed to copy file from container: {cp_err}")

                _subprocess_failed = False
                if isinstance(structured_output, dict):
                    _rc = structured_output.get("returncode")
                    if isinstance(_rc, int) and _rc != 0:
                        _subprocess_failed = True
                        _sub_stderr = structured_output.get("stderr", "")
                        logger.warning(
                            f"[DockerExecutor] Container exit_code=0 but output.returncode={_rc}, "
                            f"marking as failure. stderr={_sub_stderr!r}"
                        )

                if _subprocess_failed:
                    _sub_stderr = structured_output.get("stderr", "")
                    return {
                        "success": False,
                        "message": f"Subprocess exited with code {structured_output.get('returncode')}",
                        "stdout": stdout,
                        "stderr": stderr or _sub_stderr,
                        "result": None,
                        "output": structured_output,
                        "variables": {},
                        "file_path": None,
                    }

                return {
                    "success": True,
                    "message": "Execution completed",
                    "stdout": stdout,
                    "stderr": stderr,
                    "result": stdout.strip() if stdout.strip() else None,
                    "output": structured_output,
                    "variables": {},
                    "file_path": _file_path,
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
            # 清理容器内 /workspace 残留文件，避免污染下次执行
            try:
                from .container_pool import exec_run_in_container as _exec
                _exec(
                    container,
                    cmd=["sh", "-c", "rm -rf /workspace/* /workspace/.*  2>/dev/null || true"],
                    workdir="/",
                    demux=False,
                    use_podman=self._is_podman,
                )
            except Exception:
                pass
            self._pool.release(container, failed=exec_failed)
    
    def _run_without_pool(self, tmpdir: str, workspace_volumes: Optional[dict] = None, base_path: Optional[str] = None, user_workspace: Optional[str] = None) -> dict:
        """不使用容器池执行（创建新容器），支持 workspace 挂载。
        
        对 Docker Desktop 在 Windows 上的间歇性连接断开做重试容错。
        """
        from .container_pool import _DOCKER_TRANSIENT_ERRORS

        _RETRIES = 3
        _RETRY_DELAY = 2.0  # 秒

        last_err: Optional[Exception] = None
        for attempt in range(_RETRIES):
            try:
                return self._run_without_pool_once(tmpdir, workspace_volumes, base_path=base_path, user_workspace=user_workspace)
            except _DOCKER_TRANSIENT_ERRORS as e:
                last_err = e
                if attempt < _RETRIES - 1:
                    logger.warning(
                        f"[DockerExecutor] Transient connection error (attempt {attempt + 1}/{_RETRIES}), "
                        f"retrying in {_RETRY_DELAY}s: {e}"
                    )
                    import time
                    time.sleep(_RETRY_DELAY)
            except Exception:
                raise

        raise RuntimeError(
            f"Docker execution failed after {_RETRIES} attempts due to connection errors: {last_err}"
        )

    def _run_without_pool_once(self, tmpdir: str, workspace_volumes: Optional[dict] = None, base_path: Optional[str] = None, user_workspace: Optional[str] = None) -> dict:
        """单次尝试：创建新容器并执行，支持 workspace 挂载。
        
        挂载策略：
          session_root → /workspace (rw)  — 容器 cwd，LLM 代码读写都在这里
          tmpdir → /script (ro)           — 脚本文件
        
        执行完成后，扫描 /workspace 下的新文件，复制到用户工作目录（user_workspace）。
        这样 open('line_count.csv', 'w') 写到 /workspace/line_count.csv，
        通过 volume mount 落在 session workspace 根目录，再被复制到用户工作目录。
        """
        if workspace_volumes:
            volumes = dict(workspace_volumes)
            volumes[tmpdir] = {"bind": "/script", "mode": "ro"}
            command = ["python", "/script/script.py"]
        else:
            volumes = {tmpdir: {"bind": "/workspace", "mode": "ro"}}
            command = ["python", "/workspace/script.py"]

        container = self._client.containers.create(
            image=self.image,
            command=command,
            volumes=volumes,
            working_dir="/workspace",
            mem_limit=self.mem_limit,
            cpu_quota=self.cpu_quota,
            network_mode=self.network_mode,
            detach=True,
        )
        
        try:
            self._last_container_id = container.id
            container.start()
            result = container.wait(timeout=self.timeout)
            stdout = container.logs(stdout=True, stderr=False).decode("utf-8")
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8")
            exit_code = result.get("StatusCode", 0)
            
            # 尝试从 stdout 提取结构化输出（__OUTPUT__: 标记行协议）
            structured_output = _extract_output_from_stdout(stdout)
            # _save_binary 写文件后 _output({"__file__": path}) 输出结构化对象，填充 file_path 字段
            _file_path = None
            if exit_code == 0 and isinstance(structured_output, dict) and "__file__" in structured_output:
                _file_path = structured_output["__file__"]

            # 防御性检查：exit_code=0 但 structured_output 包含 subprocess 失败
            _effective_success = exit_code == 0
            if _effective_success and isinstance(structured_output, dict):
                _rc = structured_output.get("returncode")
                if isinstance(_rc, int) and _rc != 0:
                    _effective_success = False
                    logger.warning(
                        f"[DockerExecutor] Container exit_code=0 but output.returncode={_rc}, "
                        f"marking as failure"
                    )

            return {
                "success": _effective_success,
                "message": "Execution completed" if _effective_success else f"Container exited with code {exit_code}" if exit_code != 0 else f"Subprocess exited with code {structured_output.get('returncode', '?')}",
                "stdout": stdout,
                "stderr": stderr,
                "result": stdout.strip() if stdout.strip() and _effective_success else None,
                "output": structured_output if _effective_success else (structured_output if isinstance(structured_output, dict) else stderr),
                "variables": {},
                "file_path": _file_path if _effective_success else None,
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
