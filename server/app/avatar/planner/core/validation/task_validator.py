"""
Task Validator

Validates task structure and dependencies.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from ...models import Task, Step, StepStatus


class PlanValidationError(Exception):
    """
    Raised when a Task fails validation and cannot be safely executed.
    """
    def __init__(self, message: str) -> None:
        super().__init__(message)


class TaskValidator:
    """
    任务验证器
    
    验证任务的结构完整性和依赖关系
    """
    
    @staticmethod
    def validate(
        task: Task,
        available_skills: Mapping[str, Any],
        *,
        strict: bool = True
    ) -> None:
        """
        验证任务
        
        Args:
            task: 要验证的任务
            available_skills: 可用的技能列表
            strict: 是否严格模式
            
        Raises:
            PlanValidationError: 验证失败
        """
        if not task.steps:
            raise PlanValidationError("Task has no steps")
        
        # 验证每个步骤
        step_ids = set()
        for step in task.steps:
            # 检查步骤 ID 唯一性
            if step.id in step_ids:
                raise PlanValidationError(f"Duplicate step ID: {step.id}")
            step_ids.add(step.id)
            
            # 验证技能是否存在
            if step.skill_name not in available_skills:
                if strict:
                    raise PlanValidationError(
                        f"Unknown skill: {step.skill_name} in step {step.id}"
                    )
        
        # 验证依赖关系
        TaskValidator._validate_dependencies(task.steps)
    
    @staticmethod
    def _validate_dependencies(steps: List[Step]) -> None:
        """
        验证步骤依赖关系
        
        检查：
        1. 依赖的步骤是否存在
        2. 是否有循环依赖
        """
        step_ids = {s.id for s in steps}
        
        # 检查依赖步骤存在性
        for step in steps:
            for dep_id in step.depends_on:
                if dep_id not in step_ids:
                    raise PlanValidationError(
                        f"Step {step.id} depends on non-existent step: {dep_id}"
                    )
        
        # 检查循环依赖（拓扑排序）
        TaskValidator._check_circular_dependencies(steps)
    
    @staticmethod
    def _check_circular_dependencies(steps: List[Step]) -> None:
        """
        检查循环依赖（使用 Kahn 算法）
        """
        from collections import defaultdict, deque
        
        # 构建依赖图
        in_degree = defaultdict(int)
        graph = defaultdict(list)
        
        for step in steps:
            if step.id not in in_degree:
                in_degree[step.id] = 0
            
            for dep_id in step.depends_on:
                graph[dep_id].append(step.id)
                in_degree[step.id] += 1
        
        # Kahn 算法
        queue = deque([step_id for step_id, degree in in_degree.items() if degree == 0])
        sorted_count = 0
        
        while queue:
            node = queue.popleft()
            sorted_count += 1
            
            for neighbor in graph[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        
        # 如果排序的节点数小于总节点数，说明有环
        if sorted_count != len(steps):
            raise PlanValidationError("Circular dependency detected in task steps")
    
    @staticmethod
    def validate_execution_state(task: Task) -> None:
        """
        验证任务执行状态
        
        检查任务是否处于可执行状态
        """
        from ...models import TaskStatus
        
        if task.status in (TaskStatus.SUCCESS, TaskStatus.FAILED):
            raise PlanValidationError(
                f"Task {task.id} is already in terminal state: {task.status}"
            )

