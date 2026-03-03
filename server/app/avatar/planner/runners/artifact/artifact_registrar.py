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
        
        # 2. 检查是否使用手动注册模式
        if spec.manual_artifact_registration:
            # 技能已在 run() 中通过 ctx.register_artifact() 注册
            logger.debug(f"Skill {spec.api_name} uses manual_artifact_registration, "
                        f"skipping auto-registration")
            return
        
        # 3. 检查是否声明了产生 artifact
        if not spec.produces_artifact:
            return
        
        # 4. 声明式注册：从输出中提取路径
        if not isinstance(output, dict):
            logger.warning(
                f"Skill {spec.api_name} declares produces_artifact=True "
                f"but output is not a dict: {type(output)}"
            )
            return
        
        # 5. 使用声明的字段名读取路径
        path_field = spec.artifact_path_field or "path"
        path_val = output.get(path_field)
        
        if not path_val:
            logger.warning(
                f"Skill {spec.api_name} declares produces_artifact=True "
                f"but output has no '{path_field}' field. "
                f"Available fields: {list(output.keys())}"
            )
            return
        
        # 6. 使用声明的类型（无需推断）
        artifact_type = spec.artifact_type
        if not artifact_type:
            # 降级：推断类型
            logger.warning(f"Skill {spec.api_name} missing artifact_type, falling back to inference")
            from app.avatar.runtime.artifact.utils import infer_artifact_type
            artifact_type, subtype = infer_artifact_type(
                uri=str(path_val),
                skill_name=step.skill_name,
                output=output
            )
            artifact_type = f"{artifact_type}:{subtype}"
        
        # 7. 提取元数据
        from app.avatar.runtime.artifact.utils import extract_artifact_metadata
        
        meta = extract_artifact_metadata(
            uri=str(path_val),
            skill_name=step.skill_name,
            step_id=step.id,
            task_id=task.id if task else None,
            session_id=task_ctx.identity.session_id if task_ctx else None,
            output=output
        )
        
        # 合并技能声明的自定义 metadata
        if spec.artifact_metadata:
            meta.update(spec.artifact_metadata)
        
        # 8. 注册到 TaskContext
        step_ctx.add_artifact(
            type=artifact_type,
            uri=str(path_val),
            meta=meta
        )
        
        logger.info(f"ArtifactRegistrar: ✅ Auto-registered artifact: {path_val} (type={artifact_type})")

