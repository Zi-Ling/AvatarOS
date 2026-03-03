"""
Workflow Engine - Refactored Version

A clean workflow execution engine.

Previous file: ~653 lines
New version: ~250 lines (62% reduction)
"""
from __future__ import annotations

import time
import uuid
import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .template import WorkflowTemplate, WorkflowStage, StageType
from .models import WorkflowRun, WorkflowRunStatus, StageRun, StageRunStatus
from .stages import AITaskStageExecutor, FixedTaskStageExecutor
from .resolvers import InputResolver, ConditionEvaluator
from ..core.event_bus_wrapper import EventBusWrapper

if TYPE_CHECKING:
    from ..base import TaskPlanner
    from ..runners.dag_runner import DagRunner
    from app.avatar.runtime.events import EventBus

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """
    工作流执行引擎（重构版）
    
    职责：
    - WorkflowRun 生命周期管理
    - 调度策略委托
    - 错误处理和状态聚合
    """
    
    def __init__(
        self,
        task_planner: TaskPlanner,
        dag_runner: DagRunner,
        skill_context: Any,
        *,
        logger_instance: Optional[logging.Logger] = None,
        event_bus: Optional[EventBus] = None
    ):
        self._task_planner = task_planner
        self._dag_runner = dag_runner
        self._skill_context = skill_context
        self._logger = logger_instance or logger
        
        self.event_wrapper = EventBusWrapper(event_bus, source="workflow_engine")
        
        # 初始化阶段执行器
        self.ai_stage_executor = AITaskStageExecutor(
            task_planner,
            dag_runner,
            skill_context,
            event_bus
        )
        
        self.fixed_stage_executor = FixedTaskStageExecutor(
            dag_runner,
            skill_context,
            event_bus
        )
    
    async def execute_workflow(
        self,
        template: WorkflowTemplate,
        inputs: Optional[Dict[str, Any]] = None,
        env_context: Optional[Dict[str, Any]] = None
    ) -> WorkflowRun:
        """
        执行工作流
        
        Args:
            template: 工作流模板
            inputs: 运行时输入
            env_context: 环境上下文
            
        Returns:
            WorkflowRun 执行记录
        """
        # 1. 创建 WorkflowRun
        run = WorkflowRun(
            id=str(uuid.uuid4()),
            workflow_id=template.id,
            workflow_name=template.name,
            inputs={**template.default_inputs, **(inputs or {})}
        )
        
        run.status = WorkflowRunStatus.RUNNING
        run.start_time = time.time()
        
        self._logger.info(f"Starting workflow execution: {template.name} ({run.id})")
        
        # 2. 发送开始事件
        self.event_wrapper.publish_workflow_event("workflow_started", {
            "run_id": run.id,
            "workflow_id": template.id,
            "workflow_name": template.name
        })
        
        try:
            # 3. 串行执行阶段（按依赖顺序）
            await self._execute_stages(template, run, env_context or {})
            
            # 4. 确定最终状态
            self._finalize_status(run)
            
        except Exception as e:
            self._logger.error(f"Workflow execution error: {e}", exc_info=True)
            run.status = WorkflowRunStatus.FAILED
            run.error = str(e)
        
        finally:
            run.end_time = time.time()
            
            self._logger.info(
                f"Workflow execution completed: {template.name} "
                f"(status={run.status.value}, duration={run.duration:.2f}s)"
            )
            
            # 5. 发送完成事件
            self.event_wrapper.publish_workflow_event("workflow_completed", {
                "run_id": run.id,
                "workflow_id": template.id,
                "status": run.status.value,
                "duration": run.duration
            })
        
        return run
    
    async def _execute_stages(
        self,
        template: WorkflowTemplate,
        run: WorkflowRun,
        env_context: Dict[str, Any]
    ) -> None:
        """执行所有阶段"""
        iteration = 0
        max_iterations = len(template.stages) * 3
        
        while iteration < max_iterations:
            iteration += 1
            
            # 获取可执行的阶段
            ready_stages = self._get_ready_stages(template, run)
            
            if not ready_stages:
                # 检查是否全部完成
                all_done = all(
                    run.get_stage_run(s.id) and
                    run.get_stage_run(s.id).status in (
                        StageRunStatus.SUCCESS,
                        StageRunStatus.FAILED,
                        StageRunStatus.SKIPPED
                    )
                    for s in template.stages
                )
                
                if all_done:
                    break
                else:
                    self._logger.error("No ready stages but not all done. Breaking.")
                    break
            
            # 执行第一个准备好的阶段（串行执行）
            stage = ready_stages[0]
            
            await self._execute_stage(stage, template, run, env_context)
            
            # 检查失败处理策略
            stage_run = run.get_stage_run(stage.id)
            if stage_run and stage_run.status == StageRunStatus.FAILED:
                if stage.on_failure == "stop":
                    self._logger.error(f"Stage {stage.id} failed, stopping workflow")
                    run.status = WorkflowRunStatus.FAILED
                    break
    
    async def _execute_stage(
        self,
        stage: WorkflowStage,
        template: WorkflowTemplate,
        run: WorkflowRun,
        env_context: Dict[str, Any]
    ) -> None:
        """执行单个阶段"""
        # 创建或获取 StageRun
        stage_run = run.get_stage_run(stage.id)
        if not stage_run:
            stage_run = StageRun(
                stage_id=stage.id,
                stage_name=stage.name
            )
            run.add_stage_run(stage_run)
        
        stage_run.mark_running()
        
        self._logger.info(f"Executing stage: {stage.name} ({stage.id})")
        
        # 发送事件
        self.event_wrapper.publish_workflow_event("stage_started", {
            "run_id": run.id,
            "stage_id": stage.id,
            "stage_name": stage.name
        })
        
        try:
            # 1. 解析输入
            resolved_inputs = InputResolver.resolve(stage.inputs, run)
            stage_run.inputs = resolved_inputs
            
            # 2. 根据类型执行
            if stage.type == StageType.AI_TASK:
                outputs = await self.ai_stage_executor.execute(
                    stage, resolved_inputs, env_context
                )
            elif stage.type == StageType.FIXED_TASK:
                outputs = await self.fixed_stage_executor.execute(
                    stage, resolved_inputs, env_context
                )
            elif stage.type == StageType.MANUAL:
                self._logger.warning(f"Manual stage {stage.id} not implemented")
                stage_run.mark_skipped()
                return
            else:
                raise ValueError(f"Unsupported stage type: {stage.type}")
            
            # 3. 标记成功
            stage_run.mark_success(outputs)
            
            self._logger.info(f"Stage {stage.id} completed successfully")
            
            # 4. 发送成功事件
            self.event_wrapper.publish_workflow_event("stage_completed", {
                "run_id": run.id,
                "stage_id": stage.id,
                "status": "success"
            })
            
        except Exception as e:
            self._logger.error(f"Stage {stage.id} execution failed: {e}", exc_info=True)
            stage_run.mark_failed(str(e))
            
            # 发送失败事件
            self.event_wrapper.publish_workflow_event("stage_failed", {
                "run_id": run.id,
                "stage_id": stage.id,
                "error": str(e)
            })
    
    def _get_ready_stages(
        self,
        template: WorkflowTemplate,
        run: WorkflowRun
    ) -> List[WorkflowStage]:
        """获取可以执行的阶段"""
        ready = []
        
        for stage in template.stages:
            stage_run = run.get_stage_run(stage.id)
            
            # 已经成功、跳过或正在运行的不再执行
            if stage_run and stage_run.status in (
                StageRunStatus.SUCCESS,
                StageRunStatus.SKIPPED,
                StageRunStatus.RUNNING
            ):
                continue
            
            # 检查依赖
            can_run = True
            for dep_id in stage.depends_on:
                dep_run = run.get_stage_run(dep_id)
                if not dep_run or dep_run.status != StageRunStatus.SUCCESS:
                    can_run = False
                    break
            
            if can_run:
                # 检查条件
                if stage.condition:
                    if not ConditionEvaluator.evaluate(stage.condition, run):
                        # 条件不满足，标记为跳过
                        if not stage_run:
                            stage_run = StageRun(
                                stage_id=stage.id,
                                stage_name=stage.name
                            )
                            run.add_stage_run(stage_run)
                        stage_run.mark_skipped()
                        continue
                
                ready.append(stage)
        
        return ready
    
    def _finalize_status(self, run: WorkflowRun) -> None:
        """确定最终状态"""
        if run.status == WorkflowRunStatus.RUNNING:
            has_failed = any(
                sr.status == StageRunStatus.FAILED for sr in run.stage_runs
            )
            
            if has_failed:
                run.status = WorkflowRunStatus.FAILED
            else:
                run.status = WorkflowRunStatus.SUCCESS

