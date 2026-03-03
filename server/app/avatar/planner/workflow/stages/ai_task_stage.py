"""
AI Task Stage Executor

Executes AI-driven task stages using TaskPlanner and DagRunner.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from ...base import TaskPlanner
    from ...runners.dag_runner import DagRunner
    from app.avatar.runtime.events import EventBus

from ..template import WorkflowStage
from .stage_executor import StageExecutor


class AITaskStageExecutor(StageExecutor):
    """
    AI 任务阶段执行器
    
    策略：创建 IntentSpec，调用 TaskPlanner，然后执行
    """
    
    def __init__(
        self,
        task_planner: TaskPlanner,
        dag_runner: DagRunner,
        skill_context: Any,
        event_bus: EventBus = None
    ):
        """
        初始化 AI 任务执行器
        
        Args:
            task_planner: 任务规划器
            dag_runner: DAG 执行器
            skill_context: 技能上下文
            event_bus: 事件总线
        """
        self.task_planner = task_planner
        self.dag_runner = dag_runner
        self.skill_context = skill_context
        self.event_bus = event_bus
    
    async def execute(
        self,
        stage: WorkflowStage,
        inputs: Dict[str, Any],
        env_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        执行 AI 任务阶段
        
        Args:
            stage: 工作流阶段
            inputs: 输入数据
            env_context: 环境上下文
            
        Returns:
            输出数据
        """
        from app.avatar.intent.models import IntentSpec, IntentDomain
        
        # 1. 创建 Intent
        intent = IntentSpec(
            id=str(uuid.uuid4()),
            goal=stage.goal or stage.name,
            intent_type="workflow_stage",
            domain=IntentDomain.OTHER,
            params=inputs,
            metadata={
                "stage_id": stage.id,
                "stage_name": stage.name,
                "is_workflow_stage": True
            },
            raw_user_input=stage.goal or stage.name
        )
        
        # 2. 调用 TaskPlanner 生成 Task
        task = await self.task_planner.make_task(intent, env_context, ctx=None)
        
        # 3. 执行 Task
        result_task = await self.dag_runner.run(
            task,
            ctx=self.skill_context,
            event_bus=self.event_bus
        )
        
        # 4. 提取输出
        from ...models import TaskStatus, StepStatus
        
        if result_task.status != TaskStatus.SUCCESS:
            raise RuntimeError(f"Task execution failed with status: {result_task.status.name}")
        
        # 提取最后一个成功步骤的输出
        outputs = {}
        success_steps = [s for s in result_task.steps if s.status == StepStatus.SUCCESS]
        
        if success_steps:
            last_step = success_steps[-1]
            if last_step.result and last_step.result.output:
                output = last_step.result.output
                if isinstance(output, dict):
                    outputs.update(output)
                else:
                    outputs["result"] = output
        
        return outputs

