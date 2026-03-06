# app/avatar/runtime/executor/sandbox.py

"""
Sandbox 执行器（统一接口）

提供统一的强隔离执行环境，内部优先使用 Kata，降级到 Docker。

特点：
- 硬件级/容器级隔离
- 资源限制（CPU/内存/超时）
- 网络隔离（默认禁用）
- 文件系统隔离（只挂载工作目录）
- 完整审计（输入/输出/资源使用/文件变更）

适用场景：
- LLM 生成的动态代码
- 任何 risk_level >= EXECUTE 的任务
- 不可信的用户输入
"""

import logging
import time
import hashlib
from typing import Any, Optional, Dict, Set, List
from pathlib import Path

from .base import SkillExecutor, ExecutionStrategy
from .kata import KataExecutor
from .docker import DockerExecutor
from app.avatar.skills.base import SkillRiskLevel

logger = logging.getLogger(__name__)


class SandboxExecutor(SkillExecutor):
    """
    Sandbox 执行器（统一接口）
    
    职责：
    - 提供统一的强隔离执行环境
    - 智能选择后端（Kata 优先，Docker 降级）
    - 强制资源限制和审计
    """
    
    def __init__(
        self,
        mem_limit: str = "256m",
        cpu_quota: int = 50000,  # 50% CPU
        timeout: int = 30,
        network_enabled: bool = False,
    ):
        super().__init__()
        self.strategy = ExecutionStrategy.DOCKER  # 使用 Docker 策略标识
        self.mem_limit = mem_limit
        self.cpu_quota = cpu_quota
        self.timeout = timeout
        self.network_enabled = network_enabled
        
        # 后端执行器
        self._kata_executor: Optional[KataExecutor] = None
        self._docker_executor: Optional[DockerExecutor] = None
        self._backend: Optional[SkillExecutor] = None
        
        # 初始化后端
        self._init_backend()
    
    def _init_backend(self):
        """初始化后端执行器（Kata 优先，Docker 降级）"""
        # 尝试 Kata
        try:
            self._kata_executor = KataExecutor(
                mem_limit=self.mem_limit,
                cpu_quota=self.cpu_quota,
                timeout=self.timeout,
            )
            if self._kata_executor._available:
                self._backend = self._kata_executor
                logger.info("[SandboxExecutor] Using KataExecutor backend")
                return
        except Exception as e:
            logger.warning(f"[SandboxExecutor] Failed to init KataExecutor: {e}")
        
        # 降级到 Docker
        try:
            self._docker_executor = DockerExecutor(
                mem_limit=self.mem_limit,
                cpu_quota=self.cpu_quota,
                timeout=self.timeout,
            )
            if self._docker_executor._available:
                self._backend = self._docker_executor
                logger.info("[SandboxExecutor] Using DockerExecutor backend (Kata unavailable)")
                return
        except Exception as e:
            logger.warning(f"[SandboxExecutor] Failed to init DockerExecutor: {e}")
        
        # 都不可用
        logger.error("[SandboxExecutor] No sandbox backend available!")
        self._backend = None
    
    def health_check(self) -> bool:
        """健康检查"""
        if self._backend is None:
            return False
        return self._backend.health_check()
    
    def supports(self, skill: Any) -> bool:
        """支持所有 EXECUTE/SYSTEM 级别的 Skill"""
        if self._backend is None:
            return False
        
        try:
            return skill.spec.risk_level in [SkillRiskLevel.EXECUTE, SkillRiskLevel.SYSTEM]
        except Exception as e:
            logger.warning(f"[SandboxExecutor] Failed to check support: {e}")
            return False
    
    async def execute(self, skill: Any, input_data: Any, context: Any) -> Any:
        """
        在沙箱中执行 Skill
        
        执行流程：
        1. 审计输入
        2. 记录文件状态（执行前）
        3. 委托给后端执行器
        4. 检测文件变更
        5. 审计输出和资源使用
        
        Args:
            skill: Skill 实例
            input_data: 输入数据
            context: SkillContext
        
        Returns:
            执行结果
        """
        if self._backend is None:
            raise RuntimeError("No sandbox backend available")
        
        api_name = skill.spec.name
        
        # ========================================
        # 审计 1: 输入审计
        # ========================================
        start_time = time.time()
        self._audit_input(api_name, input_data, context)
        
        # ========================================
        # 文件变更检测 1: 记录执行前状态
        # ========================================
        file_snapshot_before = self._snapshot_files(context.base_path)
        
        # ========================================
        # 执行
        # ========================================
        try:
            logger.info(f"[SandboxExecutor] Executing {api_name} in sandbox")
            result = await self._backend.execute(skill, input_data, context)
            execution_time = time.time() - start_time
            
            # ========================================
            # 文件变更检测 2: 对比执行后状态
            # ========================================
            file_snapshot_after = self._snapshot_files(context.base_path)
            file_changes = self._detect_file_changes(file_snapshot_before, file_snapshot_after)
            
            # ========================================
            # 审计 2: 输出审计
            # ========================================
            self._audit_output(api_name, result, execution_time, success=True, file_changes=file_changes)
            
            return result
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"[SandboxExecutor] Execution failed: {api_name}, error: {e}")
            
            # 审计失败
            self._audit_output(api_name, None, execution_time, success=False, error=str(e))
            
            raise
    
    def _audit_input(self, api_name: str, input_data: Any, context: Any):
        """
        审计输入
        
        记录：
        - Skill 名称
        - 输入参数（脱敏）
        - 时间戳
        - 工作目录
        """
        # 脱敏输入
        sanitized_input = self._sanitize_data(input_data)
        
        logger.info(
            f"[SandboxExecutor] INPUT AUDIT: "
            f"skill={api_name}, "
            f"input={sanitized_input}, "
            f"base_path={context.base_path}"
        )
    
    def _audit_output(
        self,
        api_name: str,
        result: Any,
        execution_time: float,
        success: bool,
        error: Optional[str] = None,
        file_changes: Optional[Dict] = None
    ):
        """
        审计输出
        
        记录：
        - 执行结果（成功/失败）
        - 耗时
        - 输出（脱敏）
        - 错误信息
        - 文件变更
        """
        if success:
            # 脱敏输出
            sanitized_output = self._sanitize_data(result)
            
            # 格式化文件变更信息
            file_changes_str = ""
            if file_changes:
                changes_summary = []
                if file_changes["added"]:
                    changes_summary.append(f"added={len(file_changes['added'])}")
                if file_changes["modified"]:
                    changes_summary.append(f"modified={len(file_changes['modified'])}")
                if file_changes["deleted"]:
                    changes_summary.append(f"deleted={len(file_changes['deleted'])}")
                
                if changes_summary:
                    file_changes_str = f", files_changed=({', '.join(changes_summary)})"
            
            logger.info(
                f"[SandboxExecutor] OUTPUT AUDIT: "
                f"skill={api_name}, "
                f"success=True, "
                f"time={execution_time:.3f}s, "
                f"output={sanitized_output}"
                f"{file_changes_str}"
            )
            
            # 详细记录文件变更
            if file_changes and (file_changes["added"] or file_changes["modified"] or file_changes["deleted"]):
                logger.info(f"[SandboxExecutor] FILE CHANGES:")
                for path in file_changes["added"]:
                    logger.info(f"  + {path}")
                for path in file_changes["modified"]:
                    logger.info(f"  M {path}")
                for path in file_changes["deleted"]:
                    logger.info(f"  - {path}")
        else:
            logger.error(
                f"[SandboxExecutor] OUTPUT AUDIT: "
                f"skill={api_name}, "
                f"success=False, "
                f"time={execution_time:.3f}s, "
                f"error={error}"
            )
    
    def _sanitize_data(self, data: Any) -> str:
        """
        脱敏数据（优化点 8）
        
        规则：
        1. 检测敏感字段（token, key, secret, password, cookie, authorization）
        2. 长字符串截断（>200 字符）
        3. 转换为字符串表示
        """
        if data is None:
            return "None"
        
        # 如果是 Pydantic 模型，转换为字典
        if hasattr(data, 'model_dump'):
            data = data.model_dump()
        
        # 如果是字典，检查敏感字段
        if isinstance(data, dict):
            sanitized = {}
            sensitive_keys = {'token', 'key', 'secret', 'password', 'cookie', 'authorization', 'api_key'}
            
            for k, v in data.items():
                key_lower = k.lower()
                
                # 检查是否是敏感字段
                if any(sensitive in key_lower for sensitive in sensitive_keys):
                    sanitized[k] = "***REDACTED***"
                else:
                    # 截断长字符串
                    if isinstance(v, str) and len(v) > 200:
                        sanitized[k] = v[:200] + f"... (truncated, total {len(v)} chars)"
                    else:
                        sanitized[k] = v
            
            return str(sanitized)
        
        # 其他类型，转换为字符串并截断
        data_str = str(data)
        if len(data_str) > 200:
            return data_str[:200] + f"... (truncated, total {len(data_str)} chars)"
        
        return data_str
    
    def _snapshot_files(self, base_path: Path) -> Dict[str, Dict]:
        """
        记录目录下所有文件的快照（优化点 7）
        
        策略：
        - 只在 base_path 下扫描
        - 记录：路径 + size + mtime
        - 小文件（<1MB）计算 hash
        - 大文件只记录 size + mtime
        
        Returns:
            {相对路径: {"size": int, "mtime": float, "hash": str}}
        """
        snapshot = {}
        
        try:
            if not base_path.exists():
                return snapshot
            
            # 遍历所有文件
            for file_path in base_path.rglob("*"):
                if not file_path.is_file():
                    continue
                
                # 跳过隐藏文件和特殊目录
                if any(part.startswith('.') for part in file_path.parts):
                    continue
                
                try:
                    stat = file_path.stat()
                    rel_path = str(file_path.relative_to(base_path))
                    
                    file_info = {
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                    }
                    
                    # 小文件计算 hash（<1MB）
                    if stat.st_size < 1024 * 1024:
                        try:
                            with open(file_path, "rb") as f:
                                file_hash = hashlib.md5(f.read()).hexdigest()
                            file_info["hash"] = file_hash
                        except Exception:
                            # 无法读取，跳过 hash
                            pass
                    
                    snapshot[rel_path] = file_info
                
                except Exception as e:
                    logger.debug(f"[SandboxExecutor] Failed to stat file {file_path}: {e}")
        
        except Exception as e:
            logger.warning(f"[SandboxExecutor] Failed to snapshot files: {e}")
        
        return snapshot
    
    def _detect_file_changes(
        self,
        before: Dict[str, Dict],
        after: Dict[str, Dict]
    ) -> Dict[str, List[str]]:
        """
        检测文件变更
        
        Returns:
            {
                "added": [路径列表],
                "modified": [路径列表],
                "deleted": [路径列表]
            }
        """
        before_paths = set(before.keys())
        after_paths = set(after.keys())
        
        # 新增文件
        added = list(after_paths - before_paths)
        
        # 删除文件
        deleted = list(before_paths - after_paths)
        
        # 修改文件
        modified = []
        for path in before_paths & after_paths:
            before_info = before[path]
            after_info = after[path]
            
            # 优先使用 hash 对比（如果有）
            if "hash" in before_info and "hash" in after_info:
                if before_info["hash"] != after_info["hash"]:
                    modified.append(path)
            # 降级到 size + mtime 对比
            elif (before_info["size"] != after_info["size"] or 
                  before_info["mtime"] != after_info["mtime"]):
                modified.append(path)
        
        return {
            "added": sorted(added),
            "modified": sorted(modified),
            "deleted": sorted(deleted)
        }
    
    def cleanup(self):
        """清理资源"""
        if self._kata_executor:
            self._kata_executor.cleanup()
            self._kata_executor = None
        
        if self._docker_executor:
            self._docker_executor.cleanup()
            self._docker_executor = None
        
        self._backend = None
        
        logger.info("[SandboxExecutor] Cleaned up")
    
    def __del__(self):
        """析构时清理资源"""
        self.cleanup()
