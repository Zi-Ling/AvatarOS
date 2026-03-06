# app/avatar/runtime/executor/container_pool.py

"""
容器池管理器 v2

升级为真正的 Runtime Pool：
- 五态容器模型：CREATING / READY / BUSY / BROKEN / REMOVING
- 后台健康检查线程（两层检测：inspect + exec ping）
- 自动补建：ready + creating < pool_size 时触发
- acquire 只从 READY 队列拿，不拿尸体
- BUSY 中崩溃返回明确的 SandboxFailure 语义
"""

import logging
import time
import threading
import concurrent.futures
from enum import Enum
from typing import Optional, Dict, Any, List
from collections import deque
from dataclasses import dataclass, field

# Docker 连接错误类型（Windows Docker Desktop 间歇性断开）
try:
    from requests.exceptions import ConnectionError as RequestsConnectionError
    from urllib3.exceptions import ProtocolError
except ImportError:
    RequestsConnectionError = OSError
    ProtocolError = OSError

_DOCKER_TRANSIENT_ERRORS = (RequestsConnectionError, ProtocolError, ConnectionResetError, BrokenPipeError)

logger = logging.getLogger(__name__)


class ContainerState(str, Enum):
    CREATING  = "creating"
    READY     = "ready"
    BUSY      = "busy"
    BROKEN    = "broken"
    REMOVING  = "removing"
    # DRAINING = "draining"  # 预留：滚动升级用


class SandboxFailureReason(str, Enum):
    SANDBOX_DEAD        = "sandbox_dead"
    SANDBOX_TIMEOUT     = "sandbox_timeout"
    SANDBOX_EXEC_ERROR  = "sandbox_exec_error"


class SandboxFailure(RuntimeError):
    """容器执行层失败，携带明确语义供 StepRunner 决策"""
    def __init__(self, reason: SandboxFailureReason, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass
class ContainerEntry:
    """容器条目 — 不再是裸 ID，而是带完整生命周期信息的对象"""
    container: Any                          # docker container 对象
    state: ContainerState = ContainerState.CREATING
    created_at: float = field(default_factory=time.time)
    last_heartbeat_at: float = field(default_factory=time.time)
    last_checked_at: float = field(default_factory=time.time)
    last_error: Optional[str] = None
    task_count: int = 0                     # 累计执行次数（预留统计用）
    ping_skip_count: int = 0               # exec ping 因连接抖动被跳过的连续次数

    @property
    def container_id(self) -> str:
        return self.container.id

    @property
    def short_id(self) -> str:
        return self.container.short_id


class ContainerPool:
    """
    容器池管理器 v2

    内部维护四个集合：
      ready_queue   — deque[ContainerEntry]，READY 状态，可被 acquire
      busy_set      — Dict[str, ContainerEntry]，BUSY 状态，执行中
      creating_set  — Dict[str, ContainerEntry]，CREATING 状态，启动中
      broken_set    — Dict[str, ContainerEntry]，BROKEN 状态，待清理
    """

    HEALTH_CHECK_INTERVAL = 30   # 秒，后台健康检查间隔
    MAX_TASK_COUNT        = 100  # 单容器最大复用次数后强制轮换（预留）

    def __init__(
        self,
        client: Any,
        image: str,
        runtime: Optional[str] = None,
        pool_size: int = 2,
        max_idle_time: int = 300,
        mem_limit: str = "256m",
        cpu_quota: int = 50000,
    ):
        self.client       = client
        self.image        = image
        self.runtime      = runtime
        self.pool_size    = pool_size
        self.max_idle_time = max_idle_time
        self.mem_limit    = mem_limit
        self.cpu_quota    = cpu_quota

        self.ready_queue:   deque[ContainerEntry]       = deque()
        self.busy_set:      Dict[str, ContainerEntry]   = {}
        self.creating_set:  Dict[str, ContainerEntry]   = {}
        self.broken_set:    Dict[str, ContainerEntry]   = {}

        self._lock = threading.Lock()
        self._replenish_lock = threading.Lock()  # 防止并发补建堆积
        self._health_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        logger.info(
            f"[ContainerPool] Initialized (image={image}, runtime={runtime}, "
            f"pool_size={pool_size})"
        )

    # ------------------------------------------------------------------
    # 启动 / 关闭
    # ------------------------------------------------------------------

    def start(self):
        """预创建容器 + 启动后台健康检查线程"""
        logger.info("[ContainerPool] Starting...")

        for i in range(self.pool_size):
            self._spawn_container(reason="initial warmup")

        self._stop_event.clear()
        self._health_thread = threading.Thread(
            target=self._health_loop, daemon=True, name="ContainerPool-Health"
        )
        self._health_thread.start()

        logger.info(f"[ContainerPool] Started, pool_size={self.pool_size}")

    def shutdown(self):
        """停止健康检查线程，清理所有容器"""
        logger.info("[ContainerPool] Shutting down...")
        self._stop_event.set()

        if self._health_thread and self._health_thread.is_alive():
            self._health_thread.join(timeout=5)

        with self._lock:
            all_entries: List[ContainerEntry] = (
                list(self.ready_queue)
                + list(self.busy_set.values())
                + list(self.creating_set.values())
                + list(self.broken_set.values())
            )
            self.ready_queue.clear()
            self.busy_set.clear()
            self.creating_set.clear()
            self.broken_set.clear()

        for entry in all_entries:
            self._remove_container(entry, reason="shutdown")

        logger.info("[ContainerPool] Shutdown complete")

    # ------------------------------------------------------------------
    # 公共接口：acquire / release
    # ------------------------------------------------------------------

    def acquire(self, timeout: int = 10) -> Any:
        """
        从 READY 队列获取容器，返回 docker container 对象。
        超时或无健康容器时抛出 SandboxFailure(SANDBOX_DEAD)。
        """
        deadline = time.time() + timeout

        while time.time() < deadline:
            entry = None

            with self._lock:
                if self.ready_queue:
                    entry = self.ready_queue.popleft()
                    entry.state = ContainerState.BUSY
                    entry.task_count += 1
                    self.busy_set[entry.container_id] = entry

            if entry is not None:
                logger.debug(f"[ContainerPool] Acquired {entry.short_id}")
                return entry.container

            # 没有 READY 容器，等一下再试
            time.sleep(0.05)

        raise SandboxFailure(
            SandboxFailureReason.SANDBOX_DEAD,
            f"No healthy container available after {timeout}s "
            f"(ready={len(self.ready_queue)}, creating={len(self.creating_set)})"
        )

    def release(self, container: Any, failed: bool = False):
        """
        归还容器。
        failed=True 表示执行中容器崩溃，直接标 BROKEN 而不归还 READY。
        """
        cid = container.id

        with self._lock:
            entry = self.busy_set.pop(cid, None)

        if entry is None:
            logger.warning(f"[ContainerPool] release() called for unknown container {cid[:12]}")
            return

        if failed:
            self._mark_broken(entry, reason="execution failure reported by caller")
            return

        # 检查容器是否还活着（带重试）
        err = self._reload_with_retry(entry)
        if err is None and entry.container.status == "running":
            entry.state = ContainerState.READY
            entry.last_heartbeat_at = time.time()
            with self._lock:
                self.ready_queue.append(entry)
            logger.debug(f"[ContainerPool] Released {entry.short_id} → READY")
            return
        elif err is not None:
            logger.warning(f"[ContainerPool] Container {entry.short_id} dead on release: {err}")
        else:
            logger.warning(f"[ContainerPool] Container {entry.short_id} not running on release: status={entry.container.status}")

        self._mark_broken(entry, reason="dead on release")

    # ------------------------------------------------------------------
    # 后台健康检查循环
    # ------------------------------------------------------------------

    def _health_loop(self):
        """后台线程：定期健康检查 + 补建"""
        logger.info("[ContainerPool] Health loop started")

        while not self._stop_event.wait(timeout=self.HEALTH_CHECK_INTERVAL):
            try:
                self._check_ready_containers()
                self._cleanup_broken_containers()
                self._replenish_pool()
            except Exception as e:
                logger.error(f"[ContainerPool] Health loop error: {e}", exc_info=True)

        logger.info("[ContainerPool] Health loop stopped")

    # 连接重试参数（健康检查用）
    _INSPECT_RETRIES    = 2
    _INSPECT_RETRY_DELAY = 1.0   # 秒

    # spawn 重试参数（独立语义，比 inspect 等更久）
    _SPAWN_RETRIES      = 3
    _SPAWN_RETRY_DELAY  = 2.0    # 秒

    # exec ping 超时（通过 ThreadPoolExecutor 实现，不依赖 SDK timeout 参数）
    _EXEC_PING_TIMEOUT  = 3.0    # 秒

    def _reload_with_retry(self, entry: ContainerEntry) -> Optional[str]:
        """
        带重试的 container.reload()。
        返回 None 表示成功；返回错误字符串表示最终失败。
        对 Docker Desktop 在 Windows 上的间歇性连接断开做容错。
        """
        last_err = None
        for attempt in range(self._INSPECT_RETRIES + 1):
            try:
                entry.container.reload()
                return None  # 成功
            except _DOCKER_TRANSIENT_ERRORS as e:
                last_err = e
                if attempt < self._INSPECT_RETRIES:
                    logger.debug(f"[ContainerPool] {entry.short_id} inspect transient error (suppressed), retrying")
                    time.sleep(self._INSPECT_RETRY_DELAY)
            except Exception as e:
                # 非连接类错误，不重试
                return f"inspect failed: {e}"
        return f"inspect failed after {self._INSPECT_RETRIES + 1} attempts: {last_err}"

    def _check_ready_containers(self):
        """两层检测 READY 容器健康状态"""
        with self._lock:
            entries = list(self.ready_queue)

        now = time.time()
        dead_entries = []

        for entry in entries:
            entry.last_checked_at = now

            # 层 1：runtime inspect（带重试，容忍 Docker Desktop 连接抖动）
            err = self._reload_with_retry(entry)
            if err is not None:
                dead_entries.append((entry, err))
                continue
            if entry.container.status != "running":
                dead_entries.append((entry, f"status={entry.container.status}"))
                continue

            # 层 2：exec ping（通过 ThreadPoolExecutor 实现超时，不依赖 SDK timeout 参数）
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    future = ex.submit(entry.container.exec_run, ["true"])
                    try:
                        exit_code, _ = future.result(timeout=self._EXEC_PING_TIMEOUT)
                    except concurrent.futures.TimeoutError:
                        dead_entries.append((entry, f"exec ping timed out after {self._EXEC_PING_TIMEOUT}s"))
                        continue
                if exit_code != 0:
                    dead_entries.append((entry, f"exec ping exit_code={exit_code}"))
                    continue
                # ping 成功，重置跳过计数
                entry.ping_skip_count = 0
            except _DOCKER_TRANSIENT_ERRORS as e:
                # 连接抖动：累计跳过次数，超过阈值才标 BROKEN
                entry.ping_skip_count += 1
                if entry.ping_skip_count >= 3:
                    dead_entries.append((
                        entry,
                        f"exec ping skipped {entry.ping_skip_count} consecutive times: {e}"
                    ))
                else:
                    logger.debug(f"[ContainerPool] {entry.short_id} exec ping transient error (skip {entry.ping_skip_count}/3, suppressed)")
                continue
            except Exception as e:
                dead_entries.append((entry, f"exec ping failed: {e}"))
                continue

            # 健康，更新心跳
            entry.last_heartbeat_at = now

        # 把死容器从 ready_queue 移走
        if dead_entries:
            with self._lock:
                for entry, reason in dead_entries:
                    try:
                        self.ready_queue.remove(entry)
                    except ValueError:
                        pass  # 已被 acquire 拿走，忽略

            for entry, reason in dead_entries:
                logger.warning(f"[ContainerPool] {entry.short_id} failed health check: {reason}")
                self._mark_broken(entry, reason=reason)

    def _cleanup_broken_containers(self):
        """清理 BROKEN 容器"""
        with self._lock:
            to_clean = list(self.broken_set.values())

        for entry in to_clean:
            if entry.state == ContainerState.BROKEN:
                self._remove_container(entry, reason="broken cleanup")
                with self._lock:
                    self.broken_set.pop(entry.container_id, None)

    def _replenish_pool(self):
        """如果 ready + creating < pool_size，补建容器（防并发）"""
        if not self._replenish_lock.acquire(blocking=False):
            logger.debug("[ContainerPool] Replenish already in progress, skipping")
            return
        try:
            with self._lock:
                current = len(self.ready_queue) + len(self.creating_set)
                deficit = self.pool_size - current
            for _ in range(deficit):
                self._spawn_container(reason="replenish")
        finally:
            self._replenish_lock.release()

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _spawn_container(self, reason: str = ""):
        """在后台线程中创建并启动一个新容器，完成后放入 ready_queue"""
        def _create():
            container = None
            for attempt in range(self._SPAWN_RETRIES + 1):
                try:
                    container = self._create_raw_container()
                    break
                except _DOCKER_TRANSIENT_ERRORS as e:
                    if attempt < self._SPAWN_RETRIES:
                        logger.debug(
                            f"[ContainerPool] spawn transient error (attempt {attempt + 1}/{self._SPAWN_RETRIES + 1}), "
                            f"retrying in {self._SPAWN_RETRY_DELAY}s: {e}"
                        )
                        time.sleep(self._SPAWN_RETRY_DELAY)
                    else:
                        logger.error(f"[ContainerPool] Failed to spawn container ({reason}) after {self._SPAWN_RETRIES + 1} attempts: {e}")
                        return
                except Exception as e:
                    logger.error(f"[ContainerPool] Failed to spawn container ({reason}): {e}")
                    return

            if container is None:
                return

            try:
                entry = ContainerEntry(container=container, state=ContainerState.CREATING)
                with self._lock:
                    self.creating_set[entry.container_id] = entry

                for _ in range(20):  # 最多等 10s
                    container.reload()
                    if container.status == "running":
                        break
                    time.sleep(0.5)
                else:
                    raise RuntimeError(f"Container did not start in time (status={container.status})")

                entry.state = ContainerState.READY
                entry.last_heartbeat_at = time.time()
                with self._lock:
                    self.creating_set.pop(entry.container_id, None)
                    self.ready_queue.append(entry)

                logger.info(f"[ContainerPool] Spawned {entry.short_id} ({reason})")

            except Exception as e:
                logger.error(f"[ContainerPool] Failed to spawn container ({reason}): {e}")
                try:
                    with self._lock:
                        self.creating_set.pop(container.id, None)
                    container.remove(force=True)
                except Exception:
                    pass

        t = threading.Thread(target=_create, daemon=True, name="ContainerPool-Spawn")
        t.start()

    def _create_raw_container(self) -> Any:
        """创建并启动一个 sleep infinity 容器"""
        kwargs = {
            "image":        self.image,
            "command":      ["sleep", "infinity"],
            "mem_limit":    self.mem_limit,
            "cpu_quota":    self.cpu_quota,
            "network_mode": "none",
            "detach":       True,
        }
        if self.runtime:
            kwargs["runtime"] = self.runtime

        container = self.client.containers.create(**kwargs)
        container.start()
        return container

    def _mark_broken(self, entry: ContainerEntry, reason: str = ""):
        """将容器标记为 BROKEN，移入 broken_set"""
        entry.state = ContainerState.BROKEN
        entry.last_error = reason

        with self._lock:
            # 确保从其他集合移除
            self.ready_queue = deque(e for e in self.ready_queue if e.container_id != entry.container_id)
            self.busy_set.pop(entry.container_id, None)
            self.creating_set.pop(entry.container_id, None)
            self.broken_set[entry.container_id] = entry

        logger.warning(f"[ContainerPool] {entry.short_id} → BROKEN ({reason})")

    def _remove_container(self, entry: ContainerEntry, reason: str = ""):
        """强制删除容器"""
        entry.state = ContainerState.REMOVING
        try:
            entry.container.remove(force=True)
            logger.debug(f"[ContainerPool] Removed {entry.short_id} ({reason})")
        except Exception as e:
            logger.debug(f"[ContainerPool] Remove {entry.short_id} failed (ok if already gone): {e}")

    # ------------------------------------------------------------------
    # 状态查询（调试 / 监控用）
    # ------------------------------------------------------------------

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "ready":    len(self.ready_queue),
                "busy":     len(self.busy_set),
                "creating": len(self.creating_set),
                "broken":   len(self.broken_set),
            }

    def __del__(self):
        try:
            self.shutdown()
        except Exception:
            pass
