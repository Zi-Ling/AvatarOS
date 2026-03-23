# app/avatar/runtime/executor/__init__.py

"""
Skill 执行器模块

提供多种执行策略：
- LocalExecutor: 本地直接执行（SAFE 级别）
- ProcessExecutor: 进程隔离执行（READ/WRITE 级别）
- SandboxExecutor: 强隔离沙箱执行（EXECUTE/SYSTEM 级别，动态代码）
- WasmPluginExecutor: WASM 插件执行（预编译静态技能，真正的 WASM 隔离）
- WASMExecutor: WASM 沙箱执行（已弃用，使用 fallback 模式）
- KataExecutor: Kata Containers 执行（EXECUTE/SYSTEM 级别，完整功能）
- DockerExecutor: Docker 容器执行（兜底方案）
- FirecrackerExecutor: Firecracker MicroVM 执行（接口预留）

监控：
- ExecutorMetrics: Prometheus 指标收集器
- get_metrics: 获取全局指标实例
"""

from .base import SkillExecutor, ExecutionStrategy
from .local import LocalExecutor
from .process import ProcessExecutor
from .docker import DockerExecutor
from .wasm import WASMExecutor
from .wasm_plugin import WasmPluginExecutor
from .kata import KataExecutor
from .firecracker import FirecrackerExecutor
from .sandbox import SandboxExecutor
from .desktop import DesktopExecutor
from .factory import ExecutorFactory
from .metrics import ExecutorMetrics, get_metrics

__all__ = [
    "SkillExecutor",
    "ExecutionStrategy",
    "LocalExecutor",
    "ProcessExecutor",
    "DockerExecutor",
    "WASMExecutor",
    "WasmPluginExecutor",
    "KataExecutor",
    "FirecrackerExecutor",
    "SandboxExecutor",
    "DesktopExecutor",
    "ExecutorFactory",
    "ExecutorMetrics",
    "get_metrics",
]
