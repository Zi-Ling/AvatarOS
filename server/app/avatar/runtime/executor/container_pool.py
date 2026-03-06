# app/avatar/runtime/executor/container_pool.py

"""
容器池管理器

提供容器复用功能，避免每次执行都创建新容器。

特点：
- 容器预创建和复用
- 自动清理空闲容器
- 资源限制
- 线程安全

使用场景：
- DockerExecutor 和 KataExecutor 的性能优化
- 减少 cold start 延迟
"""

import logging
import time
import threading
from typing import Optional, Dict, Any
from collections import deque

logger = logging.getLogger(__name__)


class ContainerPool:
    """
    容器池管理器
    
    职责：
    - 管理容器生命周期
    - 提供容器复用
    - 自动清理空闲容器
    """
    
    def __init__(
        self,
        client: Any,
        image: str,
        runtime: Optional[str] = None,
        pool_size: int = 2,
        max_idle_time: int = 300,  # 5分钟
        mem_limit: str = "256m",
        cpu_quota: int = 50000,
    ):
        """
        初始化容器池
        
        Args:
            client: Docker 客户端
            image: 容器镜像
            runtime: 运行时（None 或 "kata"）
            pool_size: 池大小
            max_idle_time: 最大空闲时间（秒）
            mem_limit: 内存限制
            cpu_quota: CPU 配额
        """
        self.client = client
        self.image = image
        self.runtime = runtime
        self.pool_size = pool_size
        self.max_idle_time = max_idle_time
        self.mem_limit = mem_limit
        self.cpu_quota = cpu_quota
        
        # 容器池（空闲容器）
        self._idle_containers = deque()
        
        # 使用中的容器
        self._busy_containers: Dict[str, float] = {}  # {container_id: checkout_time}
        
        # 锁
        self._lock = threading.Lock()
        
        # 清理线程
        self._cleanup_thread = None
        self._stop_cleanup = False
        
        logger.info(
            f"[ContainerPool] Initialized (image={image}, runtime={runtime}, "
            f"pool_size={pool_size})"
        )
    
    def start(self):
        """启动容器池（预创建容器 + 启动清理线程）"""
        logger.info("[ContainerPool] Starting...")
        
        # 预创建容器
        for i in range(self.pool_size):
            try:
                container = self._create_container()
                self._idle_containers.append({
                    "container": container,
                    "created_at": time.time()
                })
                logger.info(f"[ContainerPool] Pre-created container {i+1}/{self.pool_size}")
            except Exception as e:
                logger.warning(f"[ContainerPool] Failed to pre-create container: {e}")
        
        # 启动清理线程
        self._stop_cleanup = False
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()
        
        logger.info(f"[ContainerPool] Started with {len(self._idle_containers)} containers")
    
    def _create_container(self) -> Any:
        """创建一个新容器（停止状态）"""
        create_kwargs = {
            "image": self.image,
            "command": ["sleep", "infinity"],  # 保持容器运行
            "mem_limit": self.mem_limit,
            "cpu_quota": self.cpu_quota,
            "network_mode": "none",
            "detach": True,
        }
        
        if self.runtime:
            create_kwargs["runtime"] = self.runtime
        
        container = self.client.containers.create(**create_kwargs)
        container.start()
        
        return container
    
    def acquire(self, timeout: int = 10) -> Optional[Any]:
        """
        获取一个容器（优化版：减少锁持有时间）
        
        Args:
            timeout: 超时时间（秒）
        
        Returns:
            容器对象，如果超时则返回 None
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            container = None
            
            # 快速获取容器（减少锁持有时间）
            with self._lock:
                # 尝试从空闲池获取
                if self._idle_containers:
                    container_info = self._idle_containers.popleft()
                    container = container_info["container"]
                    
                    # 标记为使用中
                    self._busy_containers[container.id] = time.time()
                
                # 如果池未满，创建新容器
                elif len(self._busy_containers) < self.pool_size:
                    # 在锁外创建容器（避免阻塞其他线程）
                    pass  # 稍后在锁外创建
            
            # 如果获取到容器，检查状态
            if container:
                try:
                    container.reload()
                    if container.status != "running":
                        container.start()
                    
                    logger.debug(f"[ContainerPool] Acquired container {container.short_id}")
                    return container
                
                except Exception as e:
                    logger.warning(f"[ContainerPool] Container {container.short_id} is dead: {e}")
                    # 容器已死，从使用中移除
                    with self._lock:
                        if container.id in self._busy_containers:
                            del self._busy_containers[container.id]
                    
                    # 尝试删除容器
                    try:
                        container.remove(force=True)
                    except Exception:
                        pass
                    
                    # 继续尝试获取
                    continue
            
            # 如果需要创建新容器（在锁外创建）
            with self._lock:
                total_containers = len(self._idle_containers) + len(self._busy_containers)
                should_create = total_containers < self.pool_size
            
            if should_create:
                try:
                    container = self._create_container()
                    with self._lock:
                        self._busy_containers[container.id] = time.time()
                    logger.debug(f"[ContainerPool] Created new container {container.short_id}")
                    return container
                except Exception as e:
                    logger.error(f"[ContainerPool] Failed to create container: {e}")
            
            # 等待一下再重试
            time.sleep(0.01)  # 减少到 10ms（原来 100ms）
        
        logger.warning("[ContainerPool] Acquire timeout")
        return None
    
    def release(self, container: Any):
        """
        释放容器（归还到池中）
        
        Args:
            container: 容器对象
        """
        with self._lock:
            # 从使用中移除
            if container.id in self._busy_containers:
                del self._busy_containers[container.id]
            
            # 检查容器状态
            try:
                container.reload()
                
                # 如果容器还活着，归还到空闲池
                if container.status == "running":
                    self._idle_containers.append({
                        "container": container,
                        "created_at": time.time()
                    })
                    logger.debug(f"[ContainerPool] Released container {container.short_id}")
                else:
                    # 容器已停止，删除
                    container.remove(force=True)
                    logger.debug(f"[ContainerPool] Removed stopped container {container.short_id}")
            
            except Exception as e:
                logger.warning(f"[ContainerPool] Failed to release container: {e}")
                try:
                    container.remove(force=True)
                except Exception:
                    pass
    
    def _cleanup_loop(self):
        """清理线程（定期清理空闲容器）"""
        while not self._stop_cleanup:
            try:
                time.sleep(60)  # 每分钟检查一次
                self._cleanup_idle_containers()
            except Exception as e:
                logger.error(f"[ContainerPool] Cleanup error: {e}")
    
    def _cleanup_idle_containers(self):
        """清理超时的空闲容器"""
        with self._lock:
            now = time.time()
            containers_to_remove = []
            
            # 检查空闲容器
            for container_info in list(self._idle_containers):
                idle_time = now - container_info["created_at"]
                
                if idle_time > self.max_idle_time:
                    containers_to_remove.append(container_info)
                    self._idle_containers.remove(container_info)
            
            # 删除超时容器
            for container_info in containers_to_remove:
                try:
                    container = container_info["container"]
                    container.remove(force=True)
                    logger.info(f"[ContainerPool] Cleaned up idle container {container.short_id}")
                except Exception as e:
                    logger.warning(f"[ContainerPool] Failed to cleanup container: {e}")
    
    def shutdown(self):
        """关闭容器池（清理所有容器）"""
        logger.info("[ContainerPool] Shutting down...")
        
        # 停止清理线程
        self._stop_cleanup = True
        if self._cleanup_thread and self._cleanup_thread != threading.current_thread():
            self._cleanup_thread.join(timeout=5)
        
        with self._lock:
            # 清理空闲容器
            for container_info in self._idle_containers:
                try:
                    container = container_info["container"]
                    container.remove(force=True)
                    logger.debug(f"[ContainerPool] Removed idle container {container.short_id}")
                except Exception as e:
                    logger.warning(f"[ContainerPool] Failed to remove container: {e}")
            
            self._idle_containers.clear()
            
            # 清理使用中的容器
            for container_id in list(self._busy_containers.keys()):
                try:
                    container = self.client.containers.get(container_id)
                    container.remove(force=True)
                    logger.debug(f"[ContainerPool] Removed busy container {container.short_id}")
                except Exception as e:
                    logger.warning(f"[ContainerPool] Failed to remove container: {e}")
            
            self._busy_containers.clear()
        
        logger.info("[ContainerPool] Shutdown complete")
    
    def __del__(self):
        """析构时清理资源"""
        self.shutdown()
