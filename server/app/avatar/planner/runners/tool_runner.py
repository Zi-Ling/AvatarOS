"""
ToolRunner - Tool Calling 执行器

将 LLM 返回的 tool_calls 转为 Step 执行
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, List
from dataclasses import replace

from ..base import Planner, SkillContext, StateStore
from ..models import Task, TaskStatus, Step, StepStatus
from ..models.step import StepResult
from ..core.event_bus_wrapper import EventBusWrapper
from .execution.step_executor import StepExecutor
from .artifact.artifact_registrar import ArtifactRegistrar
from app.llm.types import ToolCall

logger = logging.getLogger(__name__)

try:
    from app.avatar.runtime.events import EventBus
except ImportError:
    EventBus = None

try:
    from app.avatar.skills.guard import SkillGuard
except ImportError:
    SkillGuard = Any

try:
    from app.avatar.runtime.core import TaskContext, StepContext
except ImportError:
    TaskContext = None
    StepContext = None


class ToolRunner(Planner):
    """
    基于 Tool Calling 的执行器
    
    职责：
    - 将 tool_calls 转为 Step 对象
    - 执行步骤
    - 管理执行状态
    """
    
    def __init__(self, event_bus: Optional[EventBus] = None):
        self.event_wrapper = EventBusWrapper(event_bus, source="tool_runner")
        self.step_executor = StepExecutor(self.event_wrapper)
    
    async def run(
        self,
        task: Task,
        *,
        ctx: SkillContext,
        state: Optional[StateStore] = None,
        skill_guard: Optional[SkillGuard] = None,
        event_bus: Optional[EventBus] = None,
    ) -> Task:
        """
        执行任务（基于 tool_calls）
        
        Args:
            task: 任务对象，steps 来自 tool_calls 转换
            ctx: 技能调用上下文
            state: 状态存储（可选）
            skill_guard: 权限守卫（可选）
            event_bus: 事件总线（可选）
            
        Returns:
            Task: 更新后的任务对象
        """
        # 更新 EventBus
        if event_bus:
            self.event_wrapper.set_event_bus(event_bus)
            self.step_executor.event_bus.set_event_bus(event_bus)
        
        # 任务前检查
        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            logger.warning(f"Task {task.task_id} already finished with status {task.status}")
            return task
        
        # 发送任务开始事件
        self.event_wrapper.emit("task_start", {"task_id": task.task_id})
        
        # 更新任务状态
        task = replace(task, status=TaskStatus.RUNNING)
        if state:
            state.save_task(task)
        
        # 执行步骤
        try:
            task = await self._execute_steps(task, ctx, skill_guard, state)
            
            # 更新任务状态
            if all(s.status == StepStatus.COMPLETED for s in task.steps):
                task = replace(task, status=TaskStatus.COMPLETED)
                self.event_wrapper.emit("task_complete", {"task_id": task.task_id})
            elif any(s.status == StepStatus.FAILED for s in task.steps):
                task = replace(task, status=TaskStatus.FAILED)
                self.event_wrapper.emit("task_fail", {
                    "task_id": task.task_id,
                    "error": "One or more steps failed"
                })
            
        except Exception as e:
            logger.error(f"Task execution failed: {e}", exc_info=True)
            task = replace(task, status=TaskStatus.FAILED)
            self.event_wrapper.emit("task_fail", {
                "task_id": task.task_id,
                "error": str(e)
            })
        
        # 保存最终状态
        if state:
            state.save_task(task)
        
        return task
    
    async def _execute_steps(
        self,
        task: Task,
        ctx: SkillContext,
        skill_guard: Optional[SkillGuard],
        state: Optional[StateStore]
    ) -> Task:
        """
        执行所有步骤（顺序执行）
        
        Args:
            task: 任务对象
            ctx: 技能上下文
            skill_guard: 权限守卫
            state: 状态存储
            
        Returns:
            Task: 更新后的任务对象
        """
        updated_steps = []
        outputs = {}  # 存储步骤输出，用于后续步骤
        
        for step in task.steps:
            # 检查是否已完成
            if step.status == StepStatus.COMPLETED:
                updated_steps.append(step)
                if step.result and step.result.output:
                    outputs[step.step_id] = step.result.output
                continue
            
            # 解析参数（支持引用之前步骤的输出）
            resolved_params = self._resolve_params(step.params, outputs)
            step = replace(step, params=resolved_params)
            
            # 权限检查
            if skill_guard and not await skill_guard.is_allowed(step.skill):
                logger.warning(f"Step {step.step_id} blocked by guard: {step.skill}")
                step = replace(
                    step,
                    status=StepStatus.FAILED,
                    result=StepResult(
                        success=False,
                        output=None,
                        error="Permission denied",
                        logs=[]
                    )
                )
                updated_steps.append(step)
                break
            
            # 构建 StepContext
            step_ctx = None
            if TaskContext and StepContext:
                step_ctx = StepContext(
                    step_id=step.step_id,
                    task_id=task.task_id,
                    skill_name=step.skill,
                    params=step.params
                )
            
            # 执行步骤
            step = await self.step_executor.execute(
                step=step,
                ctx=ctx,
                step_ctx=step_ctx
            )
            
            # Artifact 注册
            if step.result and step.result.output:
                outputs[step.step_id] = step.result.output
                
                # 注册产物
                artifact_registrar = ArtifactRegistrar()
                if await artifact_registrar.should_register(step.skill, step.result.output):
                    await artifact_registrar.register(
                        skill_name=step.skill,
                        output=step.result.output,
                        task_id=task.task_id,
                        step_id=step.step_id
                    )
            
            updated_steps.append(step)
            
            # 保存中间状态
            if state:
                task = replace(task, steps=updated_steps)
                state.save_task(task)
            
            # 如果失败，停止执行
            if step.status == StepStatus.FAILED:
                break
        
        return replace(task, steps=updated_steps)
    
    def _resolve_params(
        self,
        params: Dict[str, Any],
        outputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        解析参数，支持引用之前步骤的输出
        
        格式：${step_id.field} 或 ${step_id}
        
        Args:
            params: 原始参数
            outputs: 之前步骤的输出
            
        Returns:
            Dict: 解析后的参数
        """
        resolved = {}
        
        for key, value in params.items():
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                ref = value[2:-1]  # 去掉 ${ 和 }
                
                if "." in ref:
                    step_id, field = ref.split(".", 1)
                    if step_id in outputs:
                        try:
                            resolved[key] = outputs[step_id].get(field)
                        except (AttributeError, KeyError):
                            resolved[key] = value
                    else:
                        resolved[key] = value
                else:
                    resolved[key] = outputs.get(ref, value)
            else:
                resolved[key] = value
        
        return resolved
    
    @staticmethod
    def tool_calls_to_steps(tool_calls: List[ToolCall]) -> List[Step]:
        """
        将 ToolCall 列表转为 Step 列表
        
        Args:
            tool_calls: LLM 返回的工具调用列表
            
        Returns:
            List[Step]: 步骤列表
        """
        steps = []
        for i, tc in enumerate(tool_calls):
            step = Step(
                step_id=tc.id,
                skill=tc.name,
                params=tc.arguments,
                depends_on=[],
                status=StepStatus.PENDING
            )
            steps.append(step)
        
        return steps
