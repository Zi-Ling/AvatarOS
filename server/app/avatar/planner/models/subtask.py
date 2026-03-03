"""
SubTask model for task decomposition (Orchestrator Layer)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum
from .types import SubTaskType


class SubTaskStatus(str, Enum):
    """子任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class SubTask:
    """
    子任务：Orchestrator 分解出的独立任务单元
    
    每个 SubTask 会被转换为一个 Task（包含多个 Steps）
    """
    
    id: str
    goal: str  # 子任务的独立目标
    order: int = 0
    status: SubTaskStatus = SubTaskStatus.PENDING
    
    # 【新增】子任务类型（控制技能范围和输出契约）
    type: SubTaskType = SubTaskType.GENERAL_EXECUTION
    
    # 【新增】是否允许危险技能（python.run, shell.run）
    allow_dangerous_skills: bool = False
    
    # 依赖关系
    depends_on: List[str] = field(default_factory=list)  # 依赖的其他 SubTask ID
    
    # 输入输出（用于任务间数据传递）
    inputs: Dict[str, Any] = field(default_factory=dict)  # 输入参数（可能来自其他子任务）
    expected_outputs: List[str] = field(default_factory=list)  # 预期产出的变量名
    actual_outputs: Dict[str, Any] = field(default_factory=dict)  # 实际产出结果
    
    # 执行相关
    task_id: Optional[str] = None  # 关联的 Task ID（执行时生成）
    task_result: Optional[Any] = None  # 完整的 Task 对象（执行完成后保存）
    priority: int = 0  # 优先级（数字越大越优先，支持并行执行排序）
    max_retry: int = 1  # 子任务级别的重试次数
    retry_count: int = 0
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    
    def mark_running(self) -> None:
        self.status = SubTaskStatus.RUNNING
    
    def mark_success(self, outputs: Dict[str, Any] = None) -> None:
        self.status = SubTaskStatus.SUCCESS
        if outputs:
            self.actual_outputs.update(outputs)
    
    def mark_failed(self, error: str) -> None:
        self.status = SubTaskStatus.FAILED
        self.error = error
    
    def can_run(self, completed_subtasks: Dict[str, SubTask]) -> bool:
        """
        检查是否可以运行（依赖是否满足）
        """
        if self.status != SubTaskStatus.PENDING:
            return False
        
        for dep_id in self.depends_on:
            dep = completed_subtasks.get(dep_id)
            if not dep or dep.status != SubTaskStatus.SUCCESS:
                return False
        
        return True
    
    def resolve_inputs(self, completed_subtasks: Dict[str, SubTask]) -> Dict[str, Any]:
        """
        解析输入参数中的引用（契约化版本 - 固定格式）
        
        【固定格式】（不可修改）：
        - "${subtask_id.output.field_name}" - 标准引用格式
        
        示例：
        - "${subtask_1.output.text}"
        - "${generate_content.output.content}"
        
        解析失败时：
        - 记录详细警告（包含所有可用的outputs）
        - 尝试使用标准输出字段（根据子任务类型）
        """
        import re
        import logging
        from .types import get_standard_output_field
        
        logger = logging.getLogger(__name__)
        
        # 【方案3】默认依赖推断
        if not self.inputs and self.depends_on:
            logger.info(
                f"[方案3] SubTask {self.id} has no inputs but has depends_on, "
                f"inferring inputs from dependencies"
            )
            
            # 自动从依赖的子任务提取标准输出
            for dep_id in self.depends_on:
                if dep_id in completed_subtasks:
                    dep_subtask = completed_subtasks[dep_id]
                    standard_field = get_standard_output_field(dep_subtask.type)
                    
                    if standard_field in dep_subtask.actual_outputs:
                        # 使用语义合理的键名
                        input_key = self._infer_input_key_name(dep_subtask.type)
                        self.inputs[input_key] = f"${{{dep_id}.output.{standard_field}}}"
                        logger.info(
                            f"✅ [方案3] Auto-inferred input: "
                            f"{input_key} = ${{{dep_id}.output.{standard_field}}}"
                        )
                        break  # 只使用第一个有效的依赖
        
        resolved = self.inputs.copy()
        
        # 【固定格式】: ${subtask_id.output.field_name}
        ref_pattern = re.compile(r'\$\{\s*(\w+)\.output\.(\w+)\s*\}')
        
        for key, value in list(resolved.items()):
            if not isinstance(value, str):
                continue
                
            matches = ref_pattern.findall(value)
            
            if not matches:
                # 没有引用标记，直接使用
                continue
            
            # 检查是否是完整替换（值完全是一个引用）
            is_full_replacement = (len(matches) == 1 and 
                                  value.strip() == f"${{{matches[0][0]}.output.{matches[0][1]}}}")
            
            if is_full_replacement:
                # 完整替换（保留原始类型）
                subtask_id, output_field = matches[0]
                
                if subtask_id not in completed_subtasks:
                    logger.error(
                        f"❌ Cannot resolve input '{key}': subtask '{subtask_id}' not found in completed subtasks. "
                        f"Available: {list(completed_subtasks.keys())}"
                    )
                    # 严重错误：引用了不存在的subtask
                    resolved[key] = f"[ERROR: subtask {subtask_id} not found]"
                    continue
                
                ref_subtask = completed_subtasks[subtask_id]
                
                # 优先使用指定的字段
                if output_field in ref_subtask.actual_outputs:
                    resolved[key] = ref_subtask.actual_outputs[output_field]
                else:
                    # 降级策略：标准字段 → _raw_result → result
                    standard_field = get_standard_output_field(ref_subtask.type)
                    
                    if standard_field in ref_subtask.actual_outputs:
                        resolved[key] = ref_subtask.actual_outputs[standard_field]
                        logger.debug(
                            f"[InputResolve] Field '{output_field}' not found in subtask '{subtask_id}', "
                            f"using standard field '{standard_field}'"
                        )
                    elif "_raw_result" in ref_subtask.actual_outputs:
                        # 优先使用 _raw_result（更接近原始skill输出）
                        resolved[key] = ref_subtask.actual_outputs["_raw_result"]
                        logger.debug(
                            f"[InputResolve] Field '{output_field}' not found in subtask '{subtask_id}', "
                            f"using '_raw_result'"
                        )
                    elif "result" in ref_subtask.actual_outputs:
                        # 最后降级：使用通用result
                        resolved[key] = ref_subtask.actual_outputs["result"]
                        logger.debug(
                            f"[InputResolve] Field '{output_field}' not found in subtask '{subtask_id}', "
                            f"using 'result'"
                        )
                    else:
                        logger.error(
                            f"❌ Cannot resolve '{key}': subtask '{subtask_id}' has no output field '{output_field}'. "
                            f"Available: {list(ref_subtask.actual_outputs.keys())}"
                        )
                        resolved[key] = f"[ERROR: ${subtask_id}.output.{output_field} not found]"
            else:
                # 字符串插值
                def replace_ref(match):
                    subtask_id = match.group(1)
                    output_field = match.group(2)
                    
                    if subtask_id in completed_subtasks:
                        ref_subtask = completed_subtasks[subtask_id]
                        val = ref_subtask.actual_outputs.get(output_field)
                        if val is None:
                            # 降级策略：标准字段 → _raw_result → result
                            standard_field = get_standard_output_field(ref_subtask.type)
                            val = ref_subtask.actual_outputs.get(standard_field)
                        if val is None:
                            val = ref_subtask.actual_outputs.get("_raw_result")
                        if val is None:
                            val = ref_subtask.actual_outputs.get("result")
                        return str(val) if val is not None else match.group(0)
                    return match.group(0)
                
                resolved[key] = ref_pattern.sub(replace_ref, value)
        
        return resolved
    
    def _infer_input_key_name(self, dep_type: SubTaskType) -> str:
        """
        【方案3辅助】根据依赖任务类型推断合适的输入键名
        
        Args:
            dep_type: 依赖任务的类型
        
        Returns:
            str: 推断的输入键名
        """
        if dep_type == SubTaskType.CONTENT_GENERATION:
            return "content"
        elif dep_type == SubTaskType.INFORMATION_EXTRACTION:
            return "data"
        elif dep_type == SubTaskType.FILE_IO:
            return "file_path"
        elif dep_type == SubTaskType.SYSTEM_INTERACTION:
            return "result"
        else:
            return "input"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "order": self.order,
            "status": self.status.value,
            "type": self.type.value,  # 序列化类型
            "allow_dangerous_skills": self.allow_dangerous_skills,
            "depends_on": self.depends_on,
            "inputs": self.inputs,
            "expected_outputs": self.expected_outputs,
            "actual_outputs": self.actual_outputs,
            "task_id": self.task_id,
            # task_result 不序列化（避免循环引用和过大的 payload）
            "priority": self.priority,
            "max_retry": self.max_retry,
            "retry_count": self.retry_count,
            "metadata": self.metadata,
            "error": self.error
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SubTask:
        status = data.get("status", "pending")
        if isinstance(status, str):
            status = SubTaskStatus(status)
        
        # 解析类型（兼容旧数据）
        subtask_type = data.get("type", "general_execution")
        if isinstance(subtask_type, str):
            try:
                subtask_type = SubTaskType(subtask_type)
            except ValueError:
                subtask_type = SubTaskType.GENERAL_EXECUTION
        
        return cls(
            id=data["id"],
            goal=data["goal"],
            order=data.get("order", 0),
            status=status,
            type=subtask_type,
            allow_dangerous_skills=data.get("allow_dangerous_skills", False),
            depends_on=data.get("depends_on", []),
            inputs=data.get("inputs", {}),
            expected_outputs=data.get("expected_outputs", []),
            actual_outputs=data.get("actual_outputs", {}),
            task_id=data.get("task_id"),
            priority=data.get("priority", 0),
            max_retry=data.get("max_retry", 1),
            retry_count=data.get("retry_count", 0),
            metadata=data.get("metadata", {}),
            error=data.get("error")
        )


@dataclass
class CompositeTask:
    """
    复合任务：包含多个 SubTask 的顶层任务
    """
    
    id: str
    goal: str  # 整体目标
    subtasks: List[SubTask] = field(default_factory=list)
    status: str = "pending"  # pending, running, success, failed
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_subtask(self, subtask: SubTask) -> None:
        self.subtasks.append(subtask)
    
    def get_subtask(self, subtask_id: str) -> Optional[SubTask]:
        for st in self.subtasks:
            if st.id == subtask_id:
                return st
        return None
    
    def get_ready_subtasks(self) -> List[SubTask]:
        """
        获取所有可以执行的子任务（依赖已满足且状态为PENDING）
        """
        completed = {st.id: st for st in self.subtasks if st.status == SubTaskStatus.SUCCESS}
        return [st for st in self.subtasks if st.can_run(completed)]
    
    def is_complete(self) -> bool:
        """检查所有子任务是否已完成（成功、失败或跳过）"""
        return all(
            st.status in (SubTaskStatus.SUCCESS, SubTaskStatus.FAILED, SubTaskStatus.SKIPPED)
            for st in self.subtasks
        )
    
    def has_failed(self) -> bool:
        """检查是否有子任务失败"""
        return any(st.status == SubTaskStatus.FAILED for st in self.subtasks)
    
    def get_completed_subtasks(self) -> Dict[str, SubTask]:
        """获取所有已成功完成的子任务"""
        return {st.id: st for st in self.subtasks if st.status == SubTaskStatus.SUCCESS}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "subtasks": [st.to_dict() for st in self.subtasks],
            "status": self.status,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CompositeTask:
        return cls(
            id=data["id"],
            goal=data["goal"],
            subtasks=[SubTask.from_dict(st) for st in data.get("subtasks", [])],
            status=data.get("status", "pending"),
            metadata=data.get("metadata", {})
        )

