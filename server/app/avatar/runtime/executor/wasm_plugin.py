# app/avatar/runtime/executor/wasm_plugin.py

"""
WASM 插件执行器（真正的 WASM 隔离）

这是为预编译的静态技能设计的高性能执行器。
与 WASMExecutor（fallback 模式）不同，这个执行器使用真正的 WASM 沙箱。

特点：
- 真正的 WASM 隔离（wasmtime）
- 禁用 WASI 能力（最小权限）
- 预编译插件（.wasm 文件）
- 高性能（~1-5ms）
- 无网络、无文件系统、无子进程

适用场景：
- 静态工具（regex_extract, json_parse, base64_encode）
- 纯计算任务（hash, crypto）
- 数据转换（format, validate）

不适用场景：
- 动态代码（LLM 生成的代码）→ 使用 SandboxExecutor
- 需要文件系统 → 使用 ProcessExecutor
- 需要网络 → 使用 ProcessExecutor
"""

import logging
import time
from typing import Any, Optional, Dict
from pathlib import Path

from .base import SkillExecutor, ExecutionStrategy
from app.avatar.skills.base import SkillRiskLevel

logger = logging.getLogger(__name__)


class WasmPluginExecutor(SkillExecutor):
    """
    WASM 插件执行器（真正的 WASM 隔离）
    
    职责：
    - 加载预编译的 .wasm 插件
    - 在 WASM 沙箱中执行（wasmtime）
    - 禁用所有 WASI 能力（最小权限）
    - 提供高性能执行（~1-5ms）
    """
    
    def __init__(
        self,
        plugin_dir: Optional[Path] = None,
        timeout: int = 5,  # WASM 插件应该很快
    ):
        super().__init__()
        self.strategy = ExecutionStrategy.WASM
        self.timeout = timeout
        
        # 插件目录
        if plugin_dir is None:
            plugin_dir = Path(__file__).parent / "wasm_plugins"
        self.plugin_dir = plugin_dir
        
        # 插件缓存 {skill_name: WasmModule}
        self._plugin_cache: Dict[str, Any] = {}
        
        # 检查 wasmtime 是否可用
        self._available = self._check_wasmtime()
        
        if self._available:
            logger.info("[WasmPluginExecutor] Initialized with plugin_dir: %s", self.plugin_dir)
        else:
            logger.warning("[WasmPluginExecutor] wasmtime not available, executor disabled")
    
    def _check_wasmtime(self) -> bool:
        """检查 wasmtime 是否可用"""
        try:
            import wasmtime
            return True
        except ImportError:
            logger.warning("[WasmPluginExecutor] wasmtime not installed. Install with: pip install wasmtime")
            return False
    
    def health_check(self) -> bool:
        """健康检查"""
        return self._available
    
    def supports(self, skill: Any) -> bool:
        """
        检查是否支持该 Skill
        
        支持条件：
        1. wasmtime 可用
        2. exec_class == WASM_PLUGIN
        3. 插件文件存在
        """
        if not self._available:
            return False
        
        try:
            # 检查 exec_class
            from app.avatar.skills.base import ExecutionClass
            exec_class = getattr(skill.spec.meta, 'exec_class', ExecutionClass.AUTO)
            
            if exec_class != ExecutionClass.WASM_PLUGIN:
                return False
            
            # 检查插件文件是否存在
            plugin_path = self._get_plugin_path(skill.spec.api_name)
            return plugin_path.exists()
            
        except Exception as e:
            logger.warning(f"[WasmPluginExecutor] Failed to check support: {e}")
            return False
    
    def _get_plugin_path(self, api_name: str) -> Path:
        """
        获取插件路径
        
        命名规则：{skill_name}.wasm
        例如：regex_extract.wasm, json_parse.wasm
        """
        # 将 api_name 转换为文件名（替换 . 为 _）
        plugin_name = api_name.replace(".", "_") + ".wasm"
        return self.plugin_dir / plugin_name
    
    async def execute(self, skill: Any, input_data: Any, context: Any) -> Any:
        """
        在 WASM 沙箱中执行插件
        
        执行流程：
        1. 加载插件（缓存）
        2. 序列化输入（JSON）
        3. 调用 WASM 函数
        4. 反序列化输出
        
        Args:
            skill: Skill 实例
            input_data: 输入数据
            context: SkillContext
        
        Returns:
            执行结果
        """
        if not self._available:
            raise RuntimeError("wasmtime not available")
        
        api_name = skill.spec.api_name
        plugin_path = self._get_plugin_path(api_name)
        
        if not plugin_path.exists():
            raise FileNotFoundError(f"WASM plugin not found: {plugin_path}")
        
        # ========================================
        # 1. 加载插件（缓存）
        # ========================================
        start_time = time.time()
        
        if api_name not in self._plugin_cache:
            logger.info(f"[WasmPluginExecutor] Loading plugin: {plugin_path}")
            wasm_module = self._load_plugin(plugin_path)
            self._plugin_cache[api_name] = wasm_module
        else:
            wasm_module = self._plugin_cache[api_name]
        
        # ========================================
        # 2. 执行插件
        # ========================================
        try:
            result = await self._execute_plugin(wasm_module, input_data, context)
            execution_time = time.time() - start_time
            
            logger.info(
                f"[WasmPluginExecutor] Executed {api_name} in {execution_time*1000:.2f}ms"
            )
            
            return result
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(
                f"[WasmPluginExecutor] Execution failed: {api_name}, "
                f"time={execution_time*1000:.2f}ms, error={e}"
            )
            raise
    
    def _load_plugin(self, plugin_path: Path) -> Any:
        """
        加载 WASM 插件
        
        安全配置（优化点 3）：
        - 禁用所有 WASI 预置能力
        - 不提供 preopen directory
        - 不注入 env vars
        - 不启用网络组件
        """
        import wasmtime
        
        # 创建 WASM 引擎（最小配置）
        config = wasmtime.Config()
        config.cache = True  # 启用编译缓存
        config.cranelift_opt_level = "speed"  # 优化级别
        
        engine = wasmtime.Engine(config)
        
        # 创建 Store（不提供任何 WASI 能力）
        store = wasmtime.Store(engine)
        
        # 加载模块
        module = wasmtime.Module.from_file(engine, str(plugin_path))
        
        # 创建实例（不链接任何 WASI 导入）
        # 注意：这里我们故意不使用 wasmtime.WasiConfig()
        # 这样插件就无法访问文件系统、网络、环境变量等
        linker = wasmtime.Linker(engine)
        
        # 只提供必要的内存导入（如果插件需要）
        # 不提供任何 WASI 函数
        
        instance = linker.instantiate(store, module)
        
        logger.info(f"[WasmPluginExecutor] Plugin loaded: {plugin_path.name}")
        
        return {
            "store": store,
            "instance": instance,
            "module": module,
        }
    
    async def _execute_plugin(
        self,
        wasm_module: Dict[str, Any],
        input_data: Any,
        context: Any
    ) -> Any:
        """
        执行 WASM 插件
        
        协议：
        - 插件导出函数：execute(input_ptr: i32, input_len: i32) -> i32
        - 输入：JSON 字符串（UTF-8）
        - 输出：JSON 字符串（UTF-8）
        - 返回值：输出字符串的指针
        """
        import json
        
        store = wasm_module["store"]
        instance = wasm_module["instance"]
        
        # 序列化输入
        if hasattr(input_data, 'model_dump'):
            input_dict = input_data.model_dump()
        else:
            input_dict = input_data
        
        input_json = json.dumps(input_dict)
        input_bytes = input_json.encode('utf-8')
        
        # 调用 WASM 函数
        # 注意：这里需要根据实际的插件接口调整
        # 目前这是一个占位实现
        execute_func = instance.exports(store)["execute"]
        
        # 分配内存并写入输入
        # （实际实现需要调用插件的 alloc 函数）
        # result_ptr = execute_func(store, input_ptr, len(input_bytes))
        
        # 读取输出
        # （实际实现需要从 WASM 内存中读取）
        # output_bytes = ...
        # output_json = output_bytes.decode('utf-8')
        # result = json.loads(output_json)
        
        # 占位返回
        raise NotImplementedError(
            "WASM plugin execution protocol not yet implemented. "
            "This is a placeholder for Phase 2 development."
        )
    
    def cleanup(self):
        """清理资源"""
        self._plugin_cache.clear()
        logger.info("[WasmPluginExecutor] Cleaned up plugin cache")
    
    def __del__(self):
        """析构时清理资源"""
        self.cleanup()
