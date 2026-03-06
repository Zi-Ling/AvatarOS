"""
DagRunner - Refactored Version

A clean DAG-based task executor.

Previous file: ~777 lines
New version: ~200 lines (74% reduction)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ..base import Planner, SkillContext, StateStore
from ..models import Task, TaskStatus, StepStatus
from ..graph.util import build_graph_from_steps
from ..core.parameter_engine import ParameterEngine
from ..core.event_bus_wrapper import EventBusWrapper
from .execution.step_executor import StepExecutor
from .artifact.artifact_registrar import ArtifactRegistrar
from .artifact.artifact_syncer import ArtifactSyncer
from .verification.step_verifier import StepVerifier

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


class DagRunner(Planner):
    """
    DAG-based Task Runner (Refactored)
    
    职责：
    - DAG 拓扑排序
    - 步骤依赖检查
    - 整体任务状态管理
    - 委托给子模块执行
    """
    
    def __init__(self, event_bus: Optional[EventBus] = None):
        self.event_wrapper = EventBusWrapper(event_bus, source="dag_runner")
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
        执行任务
        
        流程：
        1. 状态检查
        2. 构建 DAG
        3. 拓扑排序
        4. 逐步执行（依赖检查 → 参数解析 → 执行 → Artifact注册）
        5. 更新任务状态
        """
        # 更新 EventBus
        if event_bus:
            self.event_wrapper.set_event_bus(event_bus)
            self.step_executor.event_bus.set_event_bus(event_bus)
        
        # 1. 状态检查
        if task.status in (TaskStatus.SUCCESS, TaskStatus.FAILED):
            logger.info(f"DagRunner: Task {task.id} already in terminal state {task.status}")
            return task
        
        task.status = TaskStatus.RUNNING
        logger.info(f"DagRunner: Starting execution for Task {task.id}")
        
        # 2. 同步 TaskContext
        task_ctx = self._get_task_context(ctx)
        if task_ctx:
            task_ctx.status.total_steps = len(task.steps)
            task_ctx.status.current_step_index = 0
            task_ctx.mark_running()
        
        # 3. 发送任务分解事件
        self._emit_task_decomposed_event(task)
        
        # 4. 构建 DAG 并排序
        graph = build_graph_from_steps(task.steps)
        ordered_nodes = graph.topological_sort()
        step_index = {s.id: s for s in task.steps}
        
        # 5. 逐步执行
        for i, node in enumerate(ordered_nodes):
            step = node.payload["step"]
            
            # 检查取消标志（在每个步骤前检查）
            # 从 TaskContext.env 中获取 cancel_event
            cancel_event = None
            if task_ctx and hasattr(task_ctx, 'env') and task_ctx.env:
                cancel_event = task_ctx.env.get("cancel_event")
            
            if cancel_event and cancel_event.is_set():
                logger.warning(f"DagRunner: Task {task.id} cancelled by user")
                task.status = TaskStatus.FAILED
                # 标记所有未完成的步骤为失败
                for remaining_step in task.steps:
                    if remaining_step.status not in (StepStatus.SUCCESS, StepStatus.FAILED, StepStatus.SKIPPED):
                        remaining_step.status = StepStatus.FAILED
                        from ..models import StepResult
                        remaining_step.result = StepResult(success=False, error="Task cancelled by user")
                return task
            
            # 更新当前步骤索引
            if task_ctx:
                task_ctx.status.current_step_index = i
                task_ctx.save_snapshot()
            
            # 跳过已完成的步骤
            if step.status in (StepStatus.SUCCESS, StepStatus.SKIPPED):
                logger.debug(f"DagRunner: Skipping step {step.id} (status: {step.status})")
                # 注意：不再需要重新注入变量，ParameterEngine 会按需从 Task.steps 查找
                continue
            
            # 检查依赖
            if not self._check_dependencies(step, step_index):
                logger.debug(f"DagRunner: Step {step.id} waiting on dependencies")
                continue
            
            logger.info(f"DagRunner: Executing step {step.id} ({step.skill_name})")
            logger.debug(f"DagRunner: Executing step {step.id} ({step.skill_name}) with params: {step.params}")
            
            # 发送子任务开始事件
            self._emit_subtask_start_event(task, step, i)
            
            # 执行步骤
            await self._execute_step(step, task, ctx, skill_guard, step_index=i)
            
            logger.debug(f"DagRunner: Step {step.id} completed, status: {step.status}")
            
            # 发送子任务完成事件
            self._emit_subtask_complete_event(task, step)
            
            # 保存状态
            if state is not None:
                state.save_task(task)
        
        # 6. 更新任务状态
        self._update_task_status(task)
        
        if state is not None:
            state.save_task(task)
        
        return task
    
    async def _execute_step(
        self,
        step: Any,
        task: Task,
        ctx: SkillContext,
        skill_guard: Optional[SkillGuard] = None,
        *,
        step_index: int = 0
    ) -> None:
        """执行单个步骤（兼容旧接口）"""
        # 1. 获取 TaskContext（从 ctx 中提取）
        task_ctx = self._get_task_context(ctx)
        
        # 2. 创建 StepContext
        step_ctx = None
        if task_ctx and StepContext:
            step_ctx = StepContext(
                execution=task_ctx,
                step_id=step.id,
                step_order=step_index,
                skill_name=step.skill_name
            )
        
        # 3. 参数解析
        # Removed verbose debug logs - too noisy
        # logger.debug(f"[DagRunner] Resolving params for step {step.id}: {step.params}")
        try:
            resolved_params = ParameterEngine.resolve_params(
                step.params,
                task=task,
                task_ctx=task_ctx
            )
            # logger.debug(f"[DagRunner] Params resolved successfully for step {step.id}: {resolved_params}")
            
            # 检查是否有未解析的引用（增强版）
            self._validate_resolved_params(step, resolved_params)
            
        except Exception as e:
            logger.error(f"DagRunner: Step {step.id} param resolution failed: {e}")
            step.status = StepStatus.FAILED
            from ..models import StepResult
            step.result = StepResult(success=False, error=f"Parameter resolution failed: {str(e)}")
            return
        
        # 4. 执行（含重试逻辑）
        await self.step_executor.execute(
            step=step,
            ctx=ctx,
            task_ctx=task_ctx,
            step_ctx=step_ctx,
            resolved_params=resolved_params,
            skill_guard=skill_guard,
            step_index=step_index
        )
        
        # 5. Post-execution verification (detect "success but wrong result")
        if step.status == StepStatus.SUCCESS and step.result:
            try:
                vr = StepVerifier.verify(step.skill_name, resolved_params, step.result.output)
                if not vr.valid:
                    logger.warning(f"[DagRunner] Step {step.id} verification FAILED: {vr.reason}")
                    step.status = StepStatus.FAILED
                    from ..models.step import StepResult
                    step.result = StepResult(
                        success=False,
                        output=step.result.output,
                        error=f"Verification failed: {vr.reason}"
                    )
            except Exception as ve:
                logger.debug(f"[DagRunner] Verification error (non-fatal): {ve}")
        
        # 6. Artifact 注册
        if step.status == StepStatus.SUCCESS and step.result and step_ctx:
            await ArtifactRegistrar.register_if_needed(
                step=step,
                output=step.result.output,
                task=task,
                task_ctx=task_ctx,
                step_ctx=step_ctx
            )
            
            # 同步和索引
            await ArtifactSyncer.sync_and_index(task_ctx, step_ctx)
        
        # 7. 将步骤输出注入 TaskContext.variables（供后续步骤通过 {{step_id.field}} 引用）
        #    必须在 _execute_step 内完成，因为 AgentLoop 会直接调用此方法而绕过 run()
        if step.status == StepStatus.SUCCESS and step.result and task_ctx:
            output = step.result.output
            if output is not None:
                task_ctx.variables.set(f"step_{step.id}_output", output)
                logger.debug(f"[DagRunner] Injected step_{step.id}_output into TaskContext.variables")
                if isinstance(output, dict):
                    for field_name, field_value in output.items():
                        if not field_name.startswith("_"):
                            task_ctx.variables.set(f"step_{step.id}_{field_name}", field_value)
    
    def _check_dependencies(self, step: Any, step_index: Dict[str, Any]) -> bool:
        """检查步骤依赖是否满足"""
        for dep_id in step.depends_on:
            dep_step = step_index.get(dep_id)
            if not dep_step or dep_step.status != StepStatus.SUCCESS:
                return False
        return True
    
    def _update_task_status(self, task: Task) -> None:
        """更新任务状态"""
        has_failed = any(s.status == StepStatus.FAILED for s in task.steps)
        all_success_or_skipped = all(
            s.status in (StepStatus.SUCCESS, StepStatus.SKIPPED) for s in task.steps
        )
        
        if all_success_or_skipped and not has_failed:
            task.status = TaskStatus.SUCCESS
        elif has_failed:
            if any(s.status == StepStatus.SUCCESS for s in task.steps):
                task.status = TaskStatus.PARTIAL_SUCCESS
            else:
                task.status = TaskStatus.FAILED
        else:
            task.status = TaskStatus.RUNNING
    
    def _get_task_context(self, ctx: SkillContext) -> Optional[TaskContext]:
        """获取 TaskContext"""
        task_ctx = getattr(ctx, "execution_context", None)
        if isinstance(task_ctx, TaskContext):
            return task_ctx
        return None
    
    def _validate_resolved_params(self, step: Any, resolved_params: dict) -> None:
        """
        验证解析后的参数，检测残留的占位符
        
        Args:
            step: 当前步骤
            resolved_params: 解析后的参数
        
        Raises:
            ValueError: 如果在关键参数中检测到残留占位符
        """
        import re
        
        # 正则模式：匹配 {{...}} 和 ${...}
        placeholder_pattern = re.compile(r'\{\{[^\}]+\}\}|\$\{[^\}]+\}')
        
        # 定义关键参数：这些参数如果有残留占位符会导致严重错误
        critical_params_by_skill = {
            "file.write": ["content", "relative_path"],
            "file.append": ["content", "relative_path"],
            "file.read": ["relative_path"],
            "excel.write": ["data", "file_path"],
            "word.write": ["content", "file_path"],
            "python.run": ["code"],
            "shell.run": ["command"],
            # 可以继续添加其他关键技能和参数
        }
        
        # 获取当前技能的关键参数
        critical_params = critical_params_by_skill.get(step.skill_name, [])
        
        # 检查所有参数
        unresolved_params = {}
        for key, value in resolved_params.items():
            if isinstance(value, str):
                matches = placeholder_pattern.findall(value)
                if matches:
                    unresolved_params[key] = (value, matches)
        
        if not unresolved_params:
            return
        
        # 根据参数类型决定处理方式
        critical_unresolved = {k: v for k, v in unresolved_params.items() if k in critical_params}
        non_critical_unresolved = {k: v for k, v in unresolved_params.items() if k not in critical_params}
        
        # 对于关键参数，抛出错误
        if critical_unresolved:
            error_details = []
            for key, (value, matches) in critical_unresolved.items():
                error_details.append(f"  - Parameter '{key}': {value}")
                error_details.append(f"    Unresolved placeholders: {matches}")
            
            error_msg = (
                f"Critical parameter resolution failure in step '{step.id}' ({step.skill_name}):\n"
                + "\n".join(error_details) +
                "\n\nThis usually means:\n"
                "1. The referenced step output doesn't exist or failed\n"
                "2. The placeholder syntax is incorrect\n"
                "3. The step dependency (depends_on) is missing"
            )
            logger.error(f"[DagRunner] ❌ {error_msg}")
            raise ValueError(error_msg)
        
        # 对于非关键参数，只打印警告
        if non_critical_unresolved:
            for key, (value, matches) in non_critical_unresolved.items():
                logger.warning(
                    f"[DagRunner] ⚠️ Non-critical unresolved reference in step '{step.id}' "
                    f"param '{key}': {value} (placeholders: {matches})"
                )
                logger.warning(
                    f"[DagRunner] The step will continue execution, but may fail if this parameter is required"
                )
    
    def _emit_task_decomposed_event(self, task: Task) -> None:
        """发送任务分解事件"""
        session_id = task.metadata.get("session_id") if hasattr(task, "metadata") else None
        steps_summary = [{"id": step.id, "goal": step.skill_name} for step in task.steps]
        
        self.event_wrapper.publish_task_decomposed(steps_summary, session_id)
    
    def _emit_subtask_start_event(self, task: Task, step: Any, order: int) -> None:
        """发送子任务开始事件"""
        session_id = task.metadata.get("session_id") if hasattr(task, "metadata") else None
        
        self.event_wrapper.publish_subtask_start(
            step.id,
            step.skill_name,
            order,
            len(task.steps),
            session_id
        )
    
    def _emit_subtask_complete_event(self, task: Task, step: Any) -> None:
        """发送子任务完成事件"""
        session_id = task.metadata.get("session_id") if hasattr(task, "metadata") else None
        
        summary = "执行完成"
        raw_output = None
        duration = 0
        error = None
        
        if step.result:
            raw_output = step.result.output
            duration = getattr(step.result, 'duration', 0)
            error = step.result.error if hasattr(step.result, 'error') else None
            
            # 生成自然语言总结
            if step.status == StepStatus.SUCCESS and raw_output:
                try:
                    from ..summarizer import ResultSummarizer
                    summary = ResultSummarizer.summarize(step.skill_name, raw_output)
                except Exception as e:
                    logger.warning(f"Failed to summarize step result: {e}")
        
        self.event_wrapper.publish_subtask_complete(
            step.id,
            step.skill_name,
            summary,
            step.skill_name,
            raw_output,
            duration,
            session_id,
            error
        )

