"""
Step Validator

Validates individual step configuration and parameters.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional
from dataclasses import dataclass

from ...models import Step, Task
from .task_validator import PlanValidationError

logger = logging.getLogger(__name__)


@dataclass
class ParameterValidationResult:
    """参数校验结果"""
    success: bool
    missing_params: List[str] = None
    resolved_steps: List[str] = None
    error: Optional[str] = None
    
    def __post_init__(self):
        if self.missing_params is None:
            self.missing_params = []
        if self.resolved_steps is None:
            self.resolved_steps = []


class StepValidator:
    """
    步骤验证器
    
    验证单个步骤的配置和参数
    """
    
    @staticmethod
    def validate(
        step: Step,
        available_skills: Mapping[str, Any],
        *,
        strict: bool = True
    ) -> None:
        """
        验证步骤
        
        Args:
            step: 要验证的步骤
            available_skills: 可用的技能列表
            strict: 是否严格模式
            
        Raises:
            PlanValidationError: 验证失败
        """
        # 验证步骤 ID
        if not step.id:
            raise PlanValidationError("Step ID cannot be empty")
        
        # 验证技能名称
        if not step.skill_name:
            raise PlanValidationError(f"Step {step.id} has no skill_name")
        
        # 验证技能是否存在
        if step.skill_name not in available_skills:
            if strict:
                raise PlanValidationError(
                    f"Unknown skill: {step.skill_name} in step {step.id}"
                )
        
        # 验证参数（如果技能定义了参数 schema）
        if step.skill_name in available_skills:
            skill_spec = available_skills[step.skill_name]
            StepValidator._validate_params(step, skill_spec, strict=strict)
    
    @staticmethod
    def _validate_params(
        step: Step,
        skill_spec: Dict[str, Any],
        *,
        strict: bool = True
    ) -> None:
        """
        验证步骤参数
        
        检查必需参数是否存在（如果 skill_spec 定义了 required_params）
        """
        required_params = skill_spec.get("required_params", [])
        
        if not required_params:
            return
        
        step_params = step.params or {}
        
        missing_params = set(required_params) - set(step_params.keys())
        
        if missing_params and strict:
            raise PlanValidationError(
                f"Step {step.id} missing required parameters: {missing_params}"
            )
    
    @staticmethod
    def validate_retry_config(step: Step) -> None:
        """
        验证重试配置
        
        检查重试次数是否合理
        """
        if step.max_retry < 0:
            raise PlanValidationError(
                f"Step {step.id} has invalid max_retry: {step.max_retry}"
            )
        
        if step.max_retry > 10:
            raise PlanValidationError(
                f"Step {step.id} max_retry too high: {step.max_retry} (max: 10)"
            )
    
    @staticmethod
    def validate_and_resolve_params(
        task: Task,
        context: Dict[str, Any]
    ) -> ParameterValidationResult:
        """
        验证任务参数（规划后、执行前）
        
        Args:
            task: 要验证的任务
            context: 验证上下文（保留接口兼容性，暂未使用）
        
        Returns:
            ParameterValidationResult: 校验结果
        """
        from app.avatar.skills.registry import skill_registry
        
        all_missing = []
        
        for step in task.steps:
            # 获取 Skill 定义
            skill_cls = skill_registry.get(step.skill_name)
            if not skill_cls or not hasattr(skill_cls, "spec") or not skill_cls.spec:
                continue
            
            input_model = skill_cls.spec.input_model
            if not input_model:
                continue
            
            # 获取 Required 字段
            required = StepValidator._get_required_fields(input_model)
            if not required:
                continue
            
            # 检查缺失
            step_params = step.params or {}
            missing = [f for f in required if f not in step_params or step_params[f] is None]
            
            if missing:
                logger.warning(f"[StepValidator] Step {step.id} missing required params: {missing}")
                all_missing.extend([f"{step.id}.{f}" for f in missing])
        
        # 返回结果
        if all_missing:
            return ParameterValidationResult(
                success=False,
                missing_params=all_missing,
                resolved_steps=[],
                error=f"Required parameters missing: {', '.join(all_missing)}"
            )
        
        return ParameterValidationResult(
            success=True,
            resolved_steps=[]
        )
    
    @staticmethod
    def _get_required_fields(input_model: Any) -> List[str]:
        """获取 Pydantic 模型的 Required 字段"""
        if not hasattr(input_model, "model_fields"):
            return []
        
        required = []
        for field_name, field_info in input_model.model_fields.items():
            if field_info.is_required():
                required.append(field_name)
        
        return required

