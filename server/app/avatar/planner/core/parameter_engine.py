"""
Parameter Resolution Engine

Unified parameter resolution for both DagRunner and WorkflowEngine.
Supports various reference formats:
- Artifact references: ref://artifact_id
- Variable references: $vars.name (Simple lookup only)
- Step references: {{step_id.field}}, ${step_id.field}, ref://step_id.field
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, TYPE_CHECKING
from enum import Enum

if TYPE_CHECKING:
    from ..models import Task
    from app.avatar.runtime.core import TaskContext

logger = logging.getLogger(__name__)

# 预编译正则（避免每次调用 _resolve_string 时重复编译）
# 支持：{{step_id.field}}、{{step_id.field[N]}}、{{step_id.field[N].subfield}} 三种格式
_MUSTACHE_PATTERN = re.compile(r"\{\{(\w+)\.(\w+)(?:\[(\d+)\](?:\.(\w+))?)?\}\}")
_DOLLAR_PATTERN = re.compile(r"\$\{(\w+)\.(\w+)(?:\[(\d+)\](?:\.(\w+))?)?\}")


class ReferenceType(str, Enum):
    """参数引用类型"""
    ARTIFACT = "artifact"       # ref://artifact_id
    VARIABLE = "variable"       # $vars.x (Limited support)
    LITERAL = "literal"         # 字面值


class ParameterResolver:
    """
    Parameter Resolver
    
    Responsibilities:
    1. Resolve step references ({{step_id.field}}, ${step_id.field}) via TaskContext.variables
    2. Resolve artifact references (ref://)
    3. Resolve simple variable references ($vars.name)
    4. Support on-demand lookup from Task.steps (single source of truth)
    5. Support upstream task lookup (for subtask dependencies)
    """

    def __init__(self, task: Optional["Task"] = None, task_ctx: Optional["TaskContext"] = None):
        self.task = task
        self.task_ctx = task_ctx
        # 🎯 性能优化：缓存步骤索引，避免重复线性搜索
        self._step_index_cache: Optional[Dict[str, Any]] = None
        self._upstream_step_index_cache: Optional[Dict[str, Any]] = None

    def resolve(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        解析参数字典中的所有引用
        """
        if not params:
            return {}

        resolved: Dict[str, Any] = {}

        for key, value in params.items():
            if isinstance(value, str):
                resolved[key] = self._resolve_string(value)
            elif isinstance(value, dict):
                resolved[key] = self.resolve(value)
            elif isinstance(value, list):
                resolved[key] = [
                    self._resolve_string(item) if isinstance(item, str)
                    else self.resolve(item) if isinstance(item, dict)
                    else item
                    for item in value
                ]
            else:
                resolved[key] = value

        return resolved

    def _resolve_string(self, value: str) -> Any:
        """
        解析字符串中的引用
        """
        # 1. 尝试从 TaskContext.variables 解析步骤间引用
        #    支持 {{step_id.field}} 和 ${step_id.field} 两种语法
        
        # 1a. 完整匹配：整个值就是一个引用 → 返回原始类型（可能是 dict/list/str/None）
        for pattern in (_MUSTACHE_PATTERN, _DOLLAR_PATTERN):
            match = pattern.fullmatch(value.strip())
            if match and self.task_ctx:
                index = int(match.group(3)) if match.group(3) is not None else None
                subfield = match.group(4) if match.lastindex and match.lastindex >= 4 else None
                resolved = self._try_resolve_step_ref(match.group(1), match.group(2), value, index=index, subfield=subfield)
                # 注意：resolved 可能是 None（合法值），只有在 _try_resolve_step_ref 内部找不到步骤时才返回 None
                # 所以这里直接返回，不管是什么值（包括 None）
                return resolved
        
        # 1b. 内嵌匹配：引用嵌在更大的字符串中 → 替换为 str 后返回
        if self.task_ctx:
            resolved_value = value
            changed = False
            for pattern in (_MUSTACHE_PATTERN, _DOLLAR_PATTERN):
                for match in pattern.finditer(resolved_value):
                    step_id, field = match.group(1), match.group(2)
                    index = int(match.group(3)) if match.group(3) is not None else None
                    subfield = match.group(4) if match.lastindex and match.lastindex >= 4 else None
                    ref_value = self._try_resolve_step_ref(step_id, field, match.group(0), index=index, subfield=subfield)
                    if ref_value is not None:
                        resolved_value = resolved_value.replace(match.group(0), str(ref_value))
                        changed = True
            if changed:
                return resolved_value

        # 2. Artifact ID 引用协议 (ref://artifact_id)
        if value.startswith("ref://"):
            artifact_id = value[6:]  # strip ref://
            
            # 先尝试作为步骤引用解析（ref://step_id.field 格式）
            if self.task_ctx and "." in artifact_id:
                parts = artifact_id.split(".", 1)
                resolved = self._try_resolve_step_ref(parts[0], parts[1], value)
                if resolved is not None:
                    return resolved
            
            try:
                resolved = self._resolve_artifact_reference(artifact_id)
                logger.debug(
                    "[ParamResolver] ✅ Artifact reference resolved '%s' -> %s",
                    value, type(resolved).__name__,
                )
                return resolved
            except Exception as e:
                logger.warning(
                    "[ParamResolver] ❌ Failed to resolve artifact reference '%s': %s",
                    value, e,
                )
                return value

        # 3. 简单的变量引用 ($vars.name) - 仅作为后门保留
        if value.startswith("$vars.") and self.task_ctx:
            var_name = value[6:]
            val = self.task_ctx.variables.get(var_name)
            if val is not None:
                logger.debug(f"[ParamResolver] Resolved variable '{var_name}' -> {type(val).__name__}")
                return val

        # 4. 默认返回字面值
        return value

    def _try_resolve_step_ref(
        self,
        step_id: str,
        field: str,
        original_value: str,
        *,
        index: Optional[int] = None,
        subfield: Optional[str] = None,
    ) -> Optional[Any]:
        """
        尝试从多个数据源解析步骤间引用（按需查找）

        查找顺序（单一数据源原则）：
        1. TaskContext.variables（缓存） - 已执行步骤的输出
        2. Task.steps（源数据） - 按需从步骤结果中提取
        3. upstream_tasks（子任务间引用） - 从上游子任务的步骤中查找

        支持：
        - index: 对列表结果取 result[index]
        - subfield: 对 index 取出的 dict 再取 result[subfield]
          例如 {{s1.items[0].name}} → index=0, subfield="name"

        Returns:
            解析后的值，如果无法解析则返回 None
        """
        if not self.task_ctx:
            return None

        # ========================================
        # 查找路径 1: TaskContext.variables（缓存）
        # ========================================
        # 精确字段查找
        var_key = f"step_{step_id}_{field}"
        var_value = self.task_ctx.variables.get(var_key)
        if var_value is not None:
            logger.debug(f"[ParamResolver] ✅ Resolved '{original_value}' via variable '{var_key}'")
            return self._apply_index(var_value, index, subfield, original_value)

        # 从完整输出中取字段
        output_key = f"step_{step_id}_output"
        output_value = self.task_ctx.variables.get(output_key)
        if output_value is not None:
            # 当请求 output 字段时，从 dict 中提取 'output' 键
            if field == "output" and isinstance(output_value, dict) and 'output' in output_value:
                logger.debug(f"[ParamResolver] ✅ Resolved '{original_value}' via output dict field 'output'")
                return self._apply_index(output_value['output'], index, subfield, original_value)
            
            # 其他字段：从 dict 中提取
            if isinstance(output_value, dict) and field in output_value:
                logger.debug(f"[ParamResolver] ✅ Resolved '{original_value}' via output dict field '{field}'")
                return self._apply_index(output_value[field], index, subfield, original_value)

        # ========================================
        # 查找路径 2: Task.steps（源数据，按需查找）
        # ========================================
        if self.task and hasattr(self.task, 'steps'):
            # 🎯 性能优化：使用缓存的步骤索引，避免重复线性搜索
            if self._step_index_cache is None:
                self._step_index_cache = {step.id: step for step in self.task.steps}
            
            step = self._step_index_cache.get(step_id)
            if step:
                # 找到目标步骤，提取输出
                if step.result and hasattr(step.result, 'output'):
                    output = step.result.output
                    
                    # 尝试从输出中提取字段
                    if isinstance(output, dict) and field in output:
                        logger.debug(f"[ParamResolver] ✅ Resolved '{original_value}' from Task.steps (field '{field}')")
                        return self._apply_index(output[field], index, subfield, original_value)
                    
                    # 如果请求的是 output 字段，返回完整输出
                    if field == "output":
                        logger.debug(f"[ParamResolver] ✅ Resolved '{original_value}' from Task.steps (full output)")
                        result = output if not isinstance(output, dict) else str(output)
                        return self._apply_index(result, index, subfield, original_value)
                
                # 步骤找到但没有输出
                logger.warning(f"[ParamResolver] Step '{step_id}' found in Task.steps but has no output")
                return None

        # ========================================
        # 查找路径 3: upstream_tasks（子任务间引用）
        # ========================================
        if self.task_ctx and hasattr(self.task_ctx, '_attachments'):
            upstream_tasks = self.task_ctx._attachments.get('upstream_tasks', [])
            
            # 🎯 性能优化：使用缓存的上游步骤索引
            if upstream_tasks and self._upstream_step_index_cache is None:
                self._upstream_step_index_cache = {}
                for upstream_task in upstream_tasks:
                    if hasattr(upstream_task, 'steps'):
                        for step in upstream_task.steps:
                            self._upstream_step_index_cache[step.id] = step
            
            if self._upstream_step_index_cache:
                step = self._upstream_step_index_cache.get(step_id)
                if step:
                    # 找到上游步骤
                    if step.result and hasattr(step.result, 'output'):
                        output = step.result.output
                        
                        if isinstance(output, dict) and field in output:
                            logger.debug(f"[ParamResolver] ✅ Resolved '{original_value}' from upstream_tasks (field '{field}')")
                            return self._apply_index(output[field], index, subfield, original_value)
                        
                        if field == "output":
                            logger.debug(f"[ParamResolver] ✅ Resolved '{original_value}' from upstream_tasks (full output)")
                            result = output if not isinstance(output, dict) else str(output)
                            return self._apply_index(result, index, subfield, original_value)
                    
                    logger.warning(f"[ParamResolver] Step '{step_id}' found in upstream_tasks but has no output")
                    return None

        logger.warning(f"[ParamResolver] Step reference '{original_value}' could not be resolved from any source")
        return None

    def _apply_index(self, value: Any, index: Optional[int], subfield: Optional[str], original_value: str) -> Any:
        """
        对解析结果依次应用数组下标和子字段提取。

        - index=None, subfield=None → 直接返回 value
        - index=N               → value[N]
        - index=N, subfield="x" → value[N]["x"]（value[N] 必须是 dict）
        """
        if index is None:
            return value

        if not isinstance(value, (list, tuple)):
            logger.warning(f"[ParamResolver] Cannot apply index [{index}] to non-list '{original_value}' (type={type(value).__name__})")
            return None

        if index >= len(value):
            logger.warning(f"[ParamResolver] Index [{index}] out of range for '{original_value}' (len={len(value)})")
            return None

        item = value[index]
        logger.debug(f"[ParamResolver] Applied index [{index}] to '{original_value}'")

        if subfield is None:
            return item

        if isinstance(item, dict) and subfield in item:
            logger.debug(f"[ParamResolver] Applied subfield '{subfield}' to '{original_value}'")
            return item[subfield]

        logger.warning(f"[ParamResolver] Subfield '{subfield}' not found in item at index [{index}] for '{original_value}'")
        return None

    def _resolve_artifact_reference(self, artifact_id: str) -> Any:
        """
        解析 Artifact ID 引用
        """
        if not self.task_ctx:
            raise ValueError("Cannot resolve artifact reference without TaskContext")

        if not hasattr(self.task_ctx, "artifacts"):
            raise ValueError("TaskContext has no artifacts")

        target_artifact = None
        for artifact in self.task_ctx.artifacts.items:
            if artifact.id == artifact_id:
                target_artifact = artifact
                break

        if not target_artifact:
            raise ValueError(f"Artifact '{artifact_id}' not found in TaskContext")

        # 1. meta.value
        if "value" in target_artifact.meta:
            return target_artifact.meta["value"]

        # 2. 文件 → 返回路径
        if target_artifact.type.startswith("file"):
            return target_artifact.uri

        # 3. 变量 → 从 variables 再取一次
        if target_artifact.type.startswith("variable"):
            var_name = target_artifact.meta.get("name")
            if var_name and self.task_ctx:
                var_value = self.task_ctx.variables.get(var_name)
                if var_value is not None:
                    return var_value

        return target_artifact.uri


class ParameterEngine:
    """
    参数解析引擎（工厂类）
    """

    @staticmethod
    def create_resolver(
        task: Optional["Task"] = None,
        task_ctx: Optional["TaskContext"] = None,
    ) -> ParameterResolver:
        return ParameterResolver(task=task, task_ctx=task_ctx)

    @staticmethod
    def resolve_params(
        params: Dict[str, Any],
        task: Optional["Task"] = None,
        task_ctx: Optional["TaskContext"] = None,
    ) -> Dict[str, Any]:
        resolver = ParameterResolver(task=task, task_ctx=task_ctx)
        return resolver.resolve(params)
