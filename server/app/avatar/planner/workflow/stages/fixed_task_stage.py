"""
Fixed Task Stage Executor

Executes pre-defined task stages with fixed steps.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from ...runners.dag_runner import DagRunner
    from app.avatar.runtime.events import EventBus

from ..template import WorkflowStage
from .stage_executor import StageExecutor


class FixedTaskStageExecutor(StageExecutor):
    """
    固定任务阶段执行器
    
    策略：直接从 steps 构建 Task 并执行
    """
    
    def __init__(
        self,
        dag_runner: DagRunner,
        skill_context: Any,
        event_bus: EventBus = None
    ):
        """
        初始化固定任务执行器
        
        Args:
            dag_runner: DAG 执行器
            skill_context: 技能上下文
            event_bus: 事件总线
        """
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
        执行固定任务阶段
        
        Args:
            stage: 工作流阶段
            inputs: 输入数据
            env_context: 环境上下文
            
        Returns:
            输出数据
        """
        from ...models import Task, Step
        
        # 1. 构建 Task（修复：添加必需的 intent_id 参数）
        task = Task(
            id=str(uuid.uuid4()),
            goal=stage.name,
            steps=[],
            intent_id=None,  # workflow stage 没有关联的 intent
            metadata={
                "stage_id": stage.id,
                "stage_name": stage.name,
                "is_workflow_stage": True
            }
        )
        
        # 2. 构建 Steps
        for i, step_data in enumerate(stage.steps):
            step = Step(
                id=step_data.get("id", f"step_{i}"),
                skill_name=step_data["skill"],
                params={**step_data.get("params", {}), **inputs},  # 合并输入
                order=i,
                max_retry=step_data.get("max_retry", 0),
                depends_on=step_data.get("depends_on", [])
            )
            task.steps.append(step)
        
        # 3. 执行 Task
        result_task = await self.dag_runner.run(
            task,
            ctx=self.skill_context,
            event_bus=self.event_bus
        )
        
        # 4. 检查执行结果
        from ...models import TaskStatus, StepStatus
        
        if result_task.status != TaskStatus.SUCCESS:
            raise RuntimeError(f"Task execution failed with status: {result_task.status.name}")
        
        # 5. 提取输出
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

