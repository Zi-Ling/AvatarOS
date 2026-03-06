"""
Artifact Registrar

Handles artifact registration based on SkillSpec metadata.
Supports both declarative (auto-register) and imperative (manual) approaches.
"""
from __future__ import annotations

import logging
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.avatar.runtime.core import TaskContext, StepContext

from ...models import Step, Task

logger = logging.getLogger(__name__)


class ArtifactRegistrar:
    """
    Artifact 注册器
    
    混合方案：元数据驱动的 Artifact 注册
    
    支持两种模式：
    1. 声明式（方案 A）：技能在 SkillSpec 中声明 produces_artifact=True，框架自动注册
    2. 命令式（方案 D）：技能设置 manual_artifact_registration=True，自己调用 ctx.register_artifact()
    """
    
    @staticmethod
    async def register_if_needed(
        step: Step,
        output: Any,
        task: Task,
        task_ctx: Any,
        step_ctx: Any
    ) -> None:
        """
        根据需要注册 Artifact
        
        Args:
            step: 执行的步骤
            output: 步骤输出
            task: 任务对象
            task_ctx: TaskContext
            step_ctx: StepContext
        """
        from app.avatar.skills.registry import skill_registry
        
        # 1. 获取技能的 SkillSpec
        skill_instance = skill_registry.get(step.skill_name)
        if not skill_instance:
            return
        
        spec = skill_instance.spec
        
        # New SkillSpec has no produces_artifact / manual_artifact_registration fields.
        # Artifact registration is now handled imperatively by skills themselves via ctx.
        logger.debug(f"ArtifactRegistrar: skill {spec.name} — auto-registration skipped (new SkillSpec)")
        return

