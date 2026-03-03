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
    """

    def __init__(self, task: Optional["Task"] = None, task_ctx: Optional["TaskContext"] = None):
        self.task = task
        self.task_ctx = task_ctx

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
        
        # 1a. 完整匹配：整个值就是一个引用 → 返回原始类型（可能是 dict/list/str）
        for pattern in (_MUSTACHE_PATTERN, _DOLLAR_PATTERN):
            match = pattern.fullmatch(value.strip())
            if match and self.task_ctx:
                index = int(match.group(3)) if match.group(3) is not None else None
                subfield = match.group(4) if match.lastindex and match.lastindex >= 4 else None
                resolved = self._try_resolve_step_ref(match.group(1), match.group(2), value, index=index, subfield=subfield)
                if resolved is not None:
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
        
        # 未解析的模板语法 → 报错（强制 LLM 使用字面值）
        if ("${" in value and "}" in value) or ("{{" in value and "}}" in value):
            error_msg = (
                f"Unsupported parameter reference syntax in '{value}'. "
                f"Please use literal values or 'ref://artifact_id' for large data. "
                f"Do NOT use step references like ${{step.output}}."
            )
            logger.error(f"[ParamResolver] {error_msg}")
            raise ValueError(error_msg)

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
        尝试从 TaskContext.variables 解析步骤间引用

        查找顺序：
        1. step_{step_id}_{field} — 精确字段
        2. step_{step_id}_output[field] — 从完整输出 dict 中取字段
        3. step_{step_id}_output — 当 field == "output" 时返回完整输出

        支持：
        - index: 对列表结果取 result[index]
        - subfield: 对 index 取出的 dict 再取 result[subfield]
          例如 {{s1.items[0].name}} → index=0, subfield="name"

        Returns:
            解析后的值，如果无法解析则返回 None
        """
        if not self.task_ctx:
            return None

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
            if isinstance(output_value, dict) and field in output_value:
                logger.debug(f"[ParamResolver] ✅ Resolved '{original_value}' via output dict field '{field}'")
                return self._apply_index(output_value[field], index, subfield, original_value)
            if field == "output":
                logger.debug(f"[ParamResolver] ✅ Resolved '{original_value}' via full output")
                result = output_value if not isinstance(output_value, dict) else str(output_value)
                return self._apply_index(result, index, subfield, original_value)

        logger.warning(f"[ParamResolver] Step reference '{original_value}' could not be resolved from TaskContext")
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
