# app/avatar/runtime/executor/factory.py

"""
执行器工厂

根据 Skill 的 exec_class 和 risk_level 自动选择最优执行器。
实现智能路由逻辑、降级策略和安全 Guardrails。

核心原则：
1. 动态代码一律强隔离（SANDBOX）- 不可绕过
2. 静态技能按 exec_class 路由
3. WASM_PLUGIN 默认 fail closed

执行器优先级：
1. LocalExecutor - SAFE 级别
2. ProcessExecutor - READ/WRITE 级别
3. SandboxExecutor - EXECUTE/SYSTEM 级别（Kata 优先，Docker 兜底）
4. WasmPluginExecutor - 预编译插件（未实现）
"""

import logging
from typing import Any, Optional

from .base import SkillExecutor
from .local import LocalExecutor
from .process import ProcessExecutor
from .docker import DockerExecutor
from .wasm import WASMExecutor
from .kata import KataExecutor
from .firecracker import FirecrackerExecutor
from .sandbox import SandboxExecutor
from .wasm_plugin import WasmPluginExecutor
from app.avatar.skills.base import SkillRiskLevel, ExecutionClass

logger = logging.getLogger(__name__)


# 配置：是否允许 WASM_PLUGIN 降级到 SANDBOX（仅开发环境）
ALLOW_WASM_PLUGIN_FALLBACK = False  # 生产环境必须为 False


class ExecutorFactory:
    """
    执行器工厂
    
    职责：
    - 根据 Skill 的 risk_level 选择执行器
    - 管理执行器实例（单例模式）
    - 提供多级降级策略
    """
    
    # 单例执行器实例
    _local_executor: Optional[LocalExecutor] = None
    _process_executor: Optional[ProcessExecutor] = None
    _wasm_executor: Optional[WASMExecutor] = None
    _wasm_plugin_executor: Optional[WasmPluginExecutor] = None  # 新增
    _kata_executor: Optional[KataExecutor] = None
    _docker_executor: Optional[DockerExecutor] = None
    _firecracker_executor: Optional[FirecrackerExecutor] = None
    _sandbox_executor: Optional[SandboxExecutor] = None
    
    # 执行器优先级映射（用于 AUTO 模式）
    _executor_priority = {
        SkillRiskLevel.SAFE: ["local"],
        SkillRiskLevel.READ: ["process", "local"],  # 恢复 ProcessExecutor 优先（TaskContext 已可序列化）
        SkillRiskLevel.WRITE: ["process", "local"],  # 恢复 ProcessExecutor 优先
        SkillRiskLevel.EXECUTE: ["kata", "docker", "local"],  # 移除 WASM
        SkillRiskLevel.SYSTEM: ["kata", "docker", "local"],
    }
    
    @classmethod
    def get_executor(cls, skill: Any) -> SkillExecutor:
        """
        获取适合该 Skill 的执行器
        
        路由逻辑（按优先级）：
        1. **安全 Guardrail（不可绕过）**：
           - 如果是动态代码（risk_level >= EXECUTE 且输入有 code 字段）→ 强制 SANDBOX
        
        2. **显式声明**：
           - 如果 exec_class != AUTO → 按 exec_class 路由
           - WASM_PLUGIN 默认 fail closed（插件缺失直接报错）
        
        3. **自动推导**：
           - 如果 exec_class == AUTO → 按 risk_level 路由
        
        Args:
            skill: Skill 实例
        
        Returns:
            SkillExecutor 实例
        
        Raises:
            RuntimeError: 如果没有可用的执行器或 WASM 插件缺失
        """
        # 获取元数据
        try:
            risk_level = skill.spec.meta.risk_level
            exec_class = getattr(skill.spec.meta, 'exec_class', ExecutionClass.AUTO)
        except Exception as e:
            logger.warning(f"[ExecutorFactory] Failed to get metadata: {e}, using defaults")
            risk_level = SkillRiskLevel.SAFE
            exec_class = ExecutionClass.AUTO
        
        api_name = skill.spec.api_name
        logger.debug(f"[ExecutorFactory] Selecting executor for {api_name} (risk_level={risk_level}, exec_class={exec_class})")
        
        # ========================================
        # Guardrail 1: 动态代码强制 SANDBOX（不可绕过）
        # ========================================
        if cls._is_dynamic_code(skill, risk_level):
            logger.warning(
                f"[ExecutorFactory] 🔒 GUARDRAIL: {api_name} is dynamic code, "
                f"forcing SANDBOX execution (risk_level={risk_level})"
            )
            return cls._get_sandbox_executor()
        
        # ========================================
        # 路由 2: 显式声明的 exec_class
        # ========================================
        if exec_class != ExecutionClass.AUTO:
            return cls._route_by_exec_class(skill, exec_class, api_name)
        
        # ========================================
        # 路由 3: 自动推导（基于 risk_level）
        # ========================================
        return cls._route_by_risk_level(skill, risk_level, api_name)
    
    @classmethod
    def _is_dynamic_code(cls, skill: Any, risk_level: SkillRiskLevel) -> bool:
        """
        判断是否为动态代码（需要强制隔离）
        
        判断条件：
        1. risk_level >= EXECUTE
        2. 输入模型包含 'code' 或 'command' 或 'script' 字段
        
        这是系统级 Guardrail，防止开发者忘记标注 SANDBOX
        """
        if risk_level not in [SkillRiskLevel.EXECUTE, SkillRiskLevel.SYSTEM]:
            return False
        
        # 检查输入模型是否包含代码字段
        try:
            input_model = skill.spec.input_model
            field_names = set(input_model.model_fields.keys())
            code_fields = {'code', 'command', 'script', 'cmd'}
            
            has_code_field = bool(field_names & code_fields)
            
            if has_code_field:
                logger.debug(f"[ExecutorFactory] Detected dynamic code field in {skill.spec.api_name}")
            
            return has_code_field
        except Exception as e:
            logger.warning(f"[ExecutorFactory] Failed to check code field: {e}")
            # 保守策略：如果检查失败且 risk_level 高，则认为是动态代码
            return risk_level == SkillRiskLevel.SYSTEM
    
    @classmethod
    def _route_by_exec_class(cls, skill: Any, exec_class: ExecutionClass, api_name: str) -> SkillExecutor:
        """根据显式声明的 exec_class 路由"""
        
        if exec_class == ExecutionClass.SANDBOX:
            logger.debug(f"[ExecutorFactory] {api_name} explicitly requests SANDBOX")
            return cls._get_sandbox_executor()
        
        elif exec_class == ExecutionClass.WASM_PLUGIN:
            # 尝试使用真正的 WASM 插件执行器
            wasm_plugin_executor = cls._get_wasm_plugin_executor()
            
            if wasm_plugin_executor and wasm_plugin_executor.supports(skill):
                logger.debug(f"[ExecutorFactory] {api_name} using WasmPluginExecutor")
                return wasm_plugin_executor
            
            # Guardrail 2: WASM_PLUGIN fail closed
            logger.error(
                f"[ExecutorFactory] ❌ {api_name} requests WASM_PLUGIN but plugin not found. "
                f"Plugin file should be at: wasm_plugins/{api_name.replace('.', '_')}.wasm"
            )
            
            if ALLOW_WASM_PLUGIN_FALLBACK:
                logger.warning(f"[ExecutorFactory] ⚠️  Falling back to SANDBOX (dev mode)")
                return cls._get_sandbox_executor()
            else:
                raise RuntimeError(
                    f"WASM plugin not available for {api_name}. "
                    f"Set ALLOW_WASM_PLUGIN_FALLBACK=True in dev environment to use SANDBOX fallback."
                )
        
        elif exec_class == ExecutionClass.PROCESS:
            logger.debug(f"[ExecutorFactory] {api_name} explicitly requests PROCESS")
            return cls._get_process_executor()
        
        elif exec_class == ExecutionClass.LOCAL:
            logger.debug(f"[ExecutorFactory] {api_name} explicitly requests LOCAL")
            return cls._get_local_executor()
        
        else:
            logger.warning(f"[ExecutorFactory] Unknown exec_class: {exec_class}, using AUTO")
            return cls._route_by_risk_level(skill, skill.spec.meta.risk_level, api_name)
    
    @classmethod
    def _route_by_risk_level(cls, skill: Any, risk_level: SkillRiskLevel, api_name: str) -> SkillExecutor:
        """根据 risk_level 自动推导执行器"""
        
        priority_list = cls._executor_priority.get(risk_level, ["local"])
        logger.debug(f"[ExecutorFactory] Auto-routing {api_name} by risk_level={risk_level}")
        
        # 按优先级尝试
        for executor_type in priority_list:
            executor = cls._get_executor_instance(executor_type)
            
            if executor and executor.health_check() and executor.supports(skill):
                logger.debug(f"[ExecutorFactory] Selected {executor_type} for {api_name}")
                return executor
        
        # 最后降级到 Local（不推荐）
        logger.error(
            f"[ExecutorFactory] ⚠️  No safe executor available for {api_name}, "
            f"using LocalExecutor as last resort"
        )
        return cls._get_local_executor()
    
    @classmethod
    def _get_sandbox_executor(cls) -> SkillExecutor:
        """
        获取 SANDBOX 执行器（统一接口）
        
        这是动态代码的强制隔离执行器，内部会自动选择 Kata 或 Docker
        """
        if cls._sandbox_executor is None:
            cls._sandbox_executor = SandboxExecutor()
            logger.info("[ExecutorFactory] Created SandboxExecutor instance")
        
        return cls._sandbox_executor
    
    @classmethod
    def _get_executor_instance(cls, executor_type: str) -> Optional[SkillExecutor]:
        """获取执行器实例（单例模式）"""
        if executor_type == "local":
            return cls._get_local_executor()
        elif executor_type == "process":
            return cls._get_process_executor()
        elif executor_type == "wasm":
            return cls._get_wasm_executor()
        elif executor_type == "wasm_plugin":
            return cls._get_wasm_plugin_executor()
        elif executor_type == "kata":
            return cls._get_kata_executor()
        elif executor_type == "docker":
            return cls._get_docker_executor()
        elif executor_type == "firecracker":
            return cls._get_firecracker_executor()
        else:
            logger.warning(f"[ExecutorFactory] Unknown executor type: {executor_type}")
            return None
    
    @classmethod
    def _get_local_executor(cls) -> LocalExecutor:
        """获取 LocalExecutor 实例"""
        if cls._local_executor is None:
            cls._local_executor = LocalExecutor()
            logger.info("[ExecutorFactory] Created LocalExecutor instance")
        return cls._local_executor
    
    @classmethod
    def _get_process_executor(cls) -> ProcessExecutor:
        """获取 ProcessExecutor 实例"""
        if cls._process_executor is None:
            cls._process_executor = ProcessExecutor(max_workers=4, timeout=30)
            logger.info("[ExecutorFactory] Created ProcessExecutor instance")
        return cls._process_executor
    
    @classmethod
    def _get_wasm_executor(cls, preload: bool = False) -> Optional[WASMExecutor]:
        """
        获取 WASMExecutor 实例（fallback 模式，已废弃）
        
        Args:
            preload: 是否预加载运行时（应用启动时使用）
        """
        if cls._wasm_executor is None:
            try:
                cls._wasm_executor = WASMExecutor(timeout=30, preload=preload)
                logger.info("[ExecutorFactory] Created WASMExecutor instance")
            except Exception as e:
                logger.warning(f"[ExecutorFactory] Failed to create WASMExecutor: {e}")
                return None
        return cls._wasm_executor
    
    @classmethod
    def _get_wasm_plugin_executor(cls) -> Optional[WasmPluginExecutor]:
        """
        获取 WasmPluginExecutor 实例（真正的 WASM 隔离）
        """
        if cls._wasm_plugin_executor is None:
            try:
                cls._wasm_plugin_executor = WasmPluginExecutor(timeout=5)
                logger.info("[ExecutorFactory] Created WasmPluginExecutor instance")
            except Exception as e:
                logger.warning(f"[ExecutorFactory] Failed to create WasmPluginExecutor: {e}")
                return None
        return cls._wasm_plugin_executor
    
    @classmethod
    def preload_executors(cls):
        """
        预加载所有执行器（应用启动时调用）
        
        这会提前初始化执行器，避免首次使用时的延迟。
        适合在应用启动时调用，提升用户体验。
        
        预加载的执行器：
        - ProcessExecutor: 创建进程池并预热（避免 5.5s 延迟）
        - WASMExecutor: 预加载 Pyodide 运行时（~500ms）
        - DockerExecutor: 检查 Docker 可用性
        
        不预加载的执行器：
        - LocalExecutor: 无需预加载（0ms）
        - KataExecutor: 按需创建（避免不必要的资源占用）
        """
        logger.info("[ExecutorFactory] Preloading executors...")
        
        # 预加载 Process（最重要，避免 5.5s 延迟）
        try:
            process_executor = cls._get_process_executor()
            process_executor.warmup()  # 预热进程池
            logger.info("[ExecutorFactory] ✅ ProcessExecutor preloaded and warmed up")
        except Exception as e:
            logger.warning(f"[ExecutorFactory] ⚠️  ProcessExecutor preload failed: {e}")
        
        # 预加载 WASM（首次加载慢）
        try:
            cls._get_wasm_executor(preload=True)
            logger.info("[ExecutorFactory] ✅ WASMExecutor preloaded")
        except Exception as e:
            logger.warning(f"[ExecutorFactory] ⚠️  WASMExecutor preload failed: {e}")
        
        # 预加载 Docker（检查可用性）
        try:
            cls._get_docker_executor()
            logger.info("[ExecutorFactory] ✅ DockerExecutor preloaded")
        except Exception as e:
            logger.warning(f"[ExecutorFactory] ⚠️  DockerExecutor preload failed: {e}")
        
        # Local 无需预加载
        logger.info("[ExecutorFactory] ✅ LocalExecutor ready (no preload needed)")
        
        logger.info("[ExecutorFactory] Executor preloading completed")
    
    @classmethod
    def _get_kata_executor(cls) -> Optional[KataExecutor]:
        """获取 KataExecutor 实例"""
        if cls._kata_executor is None:
            try:
                cls._kata_executor = KataExecutor()
                logger.info("[ExecutorFactory] Created KataExecutor instance")
            except Exception as e:
                logger.warning(f"[ExecutorFactory] Failed to create KataExecutor: {e}")
                return None
        return cls._kata_executor
    
    @classmethod
    def _get_docker_executor(cls) -> Optional[DockerExecutor]:
        """获取 DockerExecutor 实例"""
        if cls._docker_executor is None:
            try:
                cls._docker_executor = DockerExecutor()
                logger.info("[ExecutorFactory] Created DockerExecutor instance")
            except Exception as e:
                logger.warning(f"[ExecutorFactory] Failed to create DockerExecutor: {e}")
                return None
        return cls._docker_executor
    
    @classmethod
    def _get_firecracker_executor(cls) -> Optional[FirecrackerExecutor]:
        """获取 FirecrackerExecutor 实例（接口预留）"""
        if cls._firecracker_executor is None:
            cls._firecracker_executor = FirecrackerExecutor()
            # 注意：FirecrackerExecutor 始终返回 supports=False
        return cls._firecracker_executor
    
    @classmethod
    def cleanup_all(cls):
        """清理所有执行器资源"""
        logger.info("[ExecutorFactory] Cleaning up all executors")
        
        if cls._process_executor:
            cls._process_executor.cleanup()
            cls._process_executor = None
        
        if cls._wasm_executor:
            cls._wasm_executor.cleanup()
            cls._wasm_executor = None
        
        if cls._wasm_plugin_executor:
            cls._wasm_plugin_executor.cleanup()
            cls._wasm_plugin_executor = None
        
        if cls._kata_executor:
            cls._kata_executor.cleanup()
            cls._kata_executor = None
        
        if cls._docker_executor:
            cls._docker_executor.cleanup()
            cls._docker_executor = None
        
        if cls._firecracker_executor:
            cls._firecracker_executor.cleanup()
            cls._firecracker_executor = None
        
        if cls._sandbox_executor:
            cls._sandbox_executor.cleanup()
            cls._sandbox_executor = None
        
        # LocalExecutor 无需清理
        cls._local_executor = None
