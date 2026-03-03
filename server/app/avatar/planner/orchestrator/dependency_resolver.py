"""
依赖解析器（DependencyResolver）

职责：
- 解析跨子任务引用（${subtask_X.output.field} 格式）
- 返回纯值（无占位符）的 inputs

注意：
- 只处理跨子任务引用（${...}）
- 步骤内引用（{{...}}）由 Planner 层的 ParamResolver 处理
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from ..models.subtask import SubTask, SubTaskStatus

logger = logging.getLogger(__name__)


class DependencyResolutionError(Exception):
    """依赖解析错误：依赖的子任务不可用或失败"""
    pass


class DependencyResolver:
    """
    依赖解析器
    
    解析子任务 inputs 中的 ${subtask_X.output.field} 占位符。
    """
    
    def resolve(
        self,
        subtask: SubTask,
        completed_subtasks: Dict[str, SubTask]
    ) -> Dict[str, Any]:
        """
        解析子任务的输入依赖
        
        将 ${subtask_X.output.field} 占位符替换为实际值。
        
        Args:
            subtask: 当前子任务
            completed_subtasks: 已完成的子任务字典 {subtask_id: SubTask}
        
        Returns:
            Dict[str, Any]: 已解析的输入（纯值，无占位符）
        
        Raises:
            DependencyResolutionError: 依赖的子任务不可用或失败
        
        示例：
            输入：{"content": "${subtask_1.output.text}"}
            输出：{"content": "实际的文本内容"}
        """
        # 🎯 [修复] 第0步：修正错误的引用格式 {{...}} -> ${...}
        self._normalize_references(subtask, completed_subtasks)
        
        # 🔥 第一步：校验依赖的子任务是否都已成功执行
        self._validate_dependencies(subtask, completed_subtasks)
        
        # 委托给 SubTask.resolve_inputs()（已实现）
        resolved = subtask.resolve_inputs(completed_subtasks)
        
        # Removed verbose debug log - too noisy
        # logger.debug(
        #     f"[DependencyResolver] Resolved inputs for {subtask.id}: "
        #     f"keys={list(resolved.keys())}"
        # )
        
        # 检查是否有未解析的占位符
        self._check_unresolved(resolved, subtask.id)
        
        return resolved
    
    def _normalize_references(
        self,
        subtask: SubTask,
        completed_subtasks: Dict[str, SubTask]
    ) -> None:
        """
        标准化引用格式
        
        将 LLM 生成的错误引用格式修正为标准格式:
        - {{content.message}} -> ${subtask_X.output.message}
        - {{content}} -> ${subtask_X.output.content}
        
        策略:
        1. 检测 {{...}} 格式的引用
        2. 如果有依赖关系,尝试将其映射到上游依赖的输出
        3. 如果找到匹配,替换为标准格式
        
        Args:
            subtask: 当前子任务
            completed_subtasks: 已完成的子任务字典
        """
        if not subtask.inputs or not subtask.depends_on:
            return
        
        import re
        
        # 检测 {{...}} 格式的引用
        double_brace_pattern = re.compile(r'\{\{([^}]+)\}\}')
        
        for input_key, input_value in list(subtask.inputs.items()):
            if not isinstance(input_value, str):
                continue
            
            matches = double_brace_pattern.findall(input_value)
            if not matches:
                continue
            
            logger.warning(
                f"[DependencyResolver] ⚠️ Detected non-standard reference format in {subtask.id}.inputs['{input_key}']: {input_value}"
            )
            
            # 尝试修正引用
            for match in matches:
                # match 可能是: "content.message" 或 "content"
                corrected = self._try_correct_reference(match, subtask.depends_on, completed_subtasks)
                
                if corrected:
                    # 替换为标准格式
                    old_ref = f"{{{{{match}}}}}"
                    new_ref = corrected
                    subtask.inputs[input_key] = input_value.replace(old_ref, new_ref)
                    
                    logger.info(
                        f"[DependencyResolver] ✅ Corrected reference: {old_ref} -> {new_ref}"
                    )
    
    def _try_correct_reference(
        self,
        expr: str,
        depends_on: list,
        completed_subtasks: Dict[str, SubTask]
    ) -> str:
        """
        尝试修正错误的引用格式
        
        Args:
            expr: 表达式 (e.g., "content.message" 或 "content")
            depends_on: 依赖的子任务 ID 列表
            completed_subtasks: 已完成的子任务字典
        
        Returns:
            str: 修正后的引用 (e.g., "${subtask_1.output.message}") 或空字符串
        """
        if not depends_on:
            return ""
        
        # 提取字段名
        parts = expr.split(".")
        field_name = parts[-1] if len(parts) > 0 else expr
        
        # 遍历依赖,查找有匹配输出字段的子任务
        for dep_id in depends_on:
            if dep_id not in completed_subtasks:
                continue
            
            dep_subtask = completed_subtasks[dep_id]
            
            # 检查该依赖是否有匹配的输出字段
            if field_name in dep_subtask.actual_outputs:
                logger.debug(
                    f"[DependencyResolver] Found matching output field '{field_name}' in {dep_id}"
                )
                return f"${{{dep_id}.output.{field_name}}}"
        
        # 如果找不到精确匹配,尝试使用第一个依赖的标准输出字段
        if depends_on:
            dep_id = depends_on[0]
            if dep_id in completed_subtasks:
                from ..models.types import get_standard_output_field
                dep_subtask = completed_subtasks[dep_id]
                standard_field = get_standard_output_field(dep_subtask.type)
                
                logger.warning(
                    f"[DependencyResolver] No exact match for '{expr}', using standard field '{standard_field}' from {dep_id}"
                )
                return f"${{{dep_id}.output.{standard_field}}}"
        
        return ""
    
    def _validate_dependencies(
        self,
        subtask: SubTask,
        completed_subtasks: Dict[str, SubTask]
    ) -> None:
        """
        校验依赖的子任务是否都已成功执行
        
        检查项：
        1. 所有 depends_on 中的子任务 ID 是否都存在
        2. 这些子任务是否都已成功执行（status == SUCCESS）
        
        Args:
            subtask: 当前子任务
            completed_subtasks: 已完成的子任务字典
        
        Raises:
            DependencyResolutionError: 依赖校验失败
        """
        if not subtask.depends_on:
            return  # 没有依赖，直接通过
        
        missing_deps = []
        failed_deps = []
        pending_deps = []
        
        for dep_id in subtask.depends_on:
            # 检查依赖是否存在
            if dep_id not in completed_subtasks:
                missing_deps.append(dep_id)
                continue
            
            dep_subtask = completed_subtasks[dep_id]
            
            # 检查依赖是否成功
            if dep_subtask.status == SubTaskStatus.FAILED:
                failed_deps.append(dep_id)
            elif dep_subtask.status != SubTaskStatus.SUCCESS:
                pending_deps.append(f"{dep_id}({dep_subtask.status.value})")
        
        # 构建错误信息
        errors = []
        if missing_deps:
            errors.append(f"Missing dependencies: {missing_deps}")
        if failed_deps:
            errors.append(f"Failed dependencies: {failed_deps}")
        if pending_deps:
            errors.append(f"Pending dependencies: {pending_deps}")
        
        if errors:
            error_msg = (
                f"[DependencyResolver] ❌ Subtask {subtask.id} dependency validation failed:\n"
                f"  Depends on: {subtask.depends_on}\n"
                f"  Available: {list(completed_subtasks.keys())}\n"
                f"  Issues: {'; '.join(errors)}"
            )
            logger.error(error_msg)
            raise DependencyResolutionError(error_msg)
        
        # 校验通过，记录调试信息
        logger.debug(
            f"[DependencyResolver] ✅ Subtask {subtask.id} dependencies validated: "
            f"{subtask.depends_on}"
        )
    
    def _check_unresolved(self, resolved: Dict[str, Any], subtask_id: str):
        """
        检查是否还有未解析的占位符
        
        如果有，记录警告（帮助调试）。
        """
        import re
        
        # 检测 ${...} 格式的占位符
        pattern = re.compile(r'\$\{[^}]+\}')
        
        for key, value in resolved.items():
            if isinstance(value, str):
                matches = pattern.findall(value)
                if matches:
                    logger.warning(
                        f"[DependencyResolver] Subtask {subtask_id} has unresolved placeholders "
                        f"in '{key}': {matches}"
                    )

