"""
Plan Validator - 执行前必经关卡

职责：
- 在 LLM 生成 steps 之后、DagRunner/StepExecutor 执行之前进行校验
- 拦截违反类型策略的技能选择、缺少必需参数的步骤
- 只负责"挡 + 说清楚为什么挡"，不负责"修"

核心规则：
1. 参数必填校验（Schema Required）：从 SkillRegistry 获取 required fields
2. SubTaskType 白名单校验：每个 type 只允许特定技能
3. Fallback 检测：包含 fallback 的计划一票否决
4. 未知技能检测：使用不存在的技能

使用位置：
Planner(LLM) -> Parsed steps -> ✅ PlanValidator.validate() -> DagRunner.execute(steps)
"""
from __future__ import annotations

import logging
from typing import List, Dict, Any, Optional, Tuple, Set, TYPE_CHECKING
from enum import Enum

if TYPE_CHECKING:
    from app.avatar.planner.models import Task, Step
    from app.avatar.planner.models.types import SubTaskType
    from app.avatar.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


class ValidationError(str, Enum):
    """验证错误类型（可观测）"""
    MISSING_REQUIRED_PARAMS = "missing_required_params"
    FORBIDDEN_SKILL = "forbidden_skill"
    UNKNOWN_SKILL = "unknown_skill"
    CONTAINS_FALLBACK = "contains_fallback"
    EMPTY_PARAMS = "empty_params"
    TYPE_CONSTRAINT_VIOLATION = "type_constraint_violation"


class ValidationResult:
    """验证结果"""
    
    def __init__(
        self,
        is_valid: bool,
        error_type: Optional[ValidationError] = None,
        detail: str = "",
        failed_step_id: Optional[str] = None,
        hint: str = ""
    ):
        self.is_valid = is_valid
        self.error_type = error_type
        self.detail = detail
        self.failed_step_id = failed_step_id
        self.hint = hint  # 给 LLM 的纠错提示
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "error_type": self.error_type.value if self.error_type else None,
            "detail": self.detail,
            "failed_step_id": self.failed_step_id,
            "hint": self.hint
        }


class PlanValidator:
    """
    计划校验器（执行前必经关卡）
    
    目标：成为"执行前必经关卡"，拦截所有不可执行/不合规的计划
    """
    
    # Fallback 技能列表（包含这些技能的计划一票否决）
    FALLBACK_SKILLS = {"llm.fallback", "fallback"}
    
    # 统计信息
    _stats = {
        "validate_pass": 0,
        "validate_block": 0,
        "blocked_reasons": {},  # {error_type: count}
        "blocked_skills": {},   # {skill_name: count}
        "missing_fields": {}    # {field_name: count}
    }
    
    def __init__(self, skill_registry: SkillRegistry):
        """
        Args:
            skill_registry: 技能注册表（用于获取 schema 和验证技能存在性）
        """
        self.registry = skill_registry
    
    # ========== 核心验证接口 ========== #
    
    def validate(
        self,
        steps: List[Step],
        subtask_type: Optional[SubTaskType] = None,
        task_id: Optional[str] = None
    ) -> ValidationResult:
        """
        验证计划是否可执行
        
        Args:
            steps: 步骤列表
            subtask_type: 子任务类型（用于白名单校验）
            task_id: 任务 ID（用于日志）
        
        Returns:
            ValidationResult: 验证结果
        """
        if not steps:
            return ValidationResult(
                is_valid=False,
                error_type=ValidationError.EMPTY_PARAMS,
                detail="Plan has no steps"
            )
        
        # 1. Fallback 检测（一票否决）
        result = self._check_fallback(steps)
        if not result.is_valid:
            self._record_block(result, task_id)
            return result
        
        # 2. 未知技能检测
        result = self._check_unknown_skills(steps)
        if not result.is_valid:
            self._record_block(result, task_id)
            return result
        
        # 3. 参数必填校验（Schema Required）
        result = self._check_required_params(steps)
        if not result.is_valid:
            self._record_block(result, task_id)
            return result
        
        # 4. SubTaskType 白名单校验（如果提供了 subtask_type）
        if subtask_type is not None:
            result = self._check_type_constraints(steps, subtask_type)
            if not result.is_valid:
                self._record_block(result, task_id)
                return result
        
        # 全部通过
        self._stats["validate_pass"] += 1
        logger.debug(f"✅ PlanValidator PASS: {len(steps)} steps validated (task={task_id})")
        
        return ValidationResult(is_valid=True)
    
    # ========== 具体校验规则 ========== #
    
    def _check_fallback(self, steps: List[Step]) -> ValidationResult:
        """检测是否包含 fallback 技能"""
        for step in steps:
            if step.skill_name in self.FALLBACK_SKILLS:
                return ValidationResult(
                    is_valid=False,
                    error_type=ValidationError.CONTAINS_FALLBACK,
                    detail=f"Plan contains fallback skill: {step.skill_name}",
                    failed_step_id=step.id,
                    hint=f"不应使用 {step.skill_name}，请生成具体的任务执行步骤"
                )
        return ValidationResult(is_valid=True)
    
    def _check_unknown_skills(self, steps: List[Step]) -> ValidationResult:
        """检测是否使用了不存在的技能"""
        for step in steps:
            skill_cls = self.registry.get(step.skill_name)
            if skill_cls is None:
                return ValidationResult(
                    is_valid=False,
                    error_type=ValidationError.UNKNOWN_SKILL,
                    detail=f"Unknown skill: {step.skill_name}",
                    failed_step_id=step.id,
                    hint=f"技能 {step.skill_name} 不存在，请从可用技能列表中选择"
                )
        return ValidationResult(is_valid=True)
    
    def _check_required_params(self, steps: List[Step]) -> ValidationResult:
        """
        检查必需参数是否完整（使用 SkillRegistry 的 schema）
        
        这是"参数必填校验"的核心实现。
        """
        for step in steps:
            skill_cls = self.registry.get(step.skill_name)
            if skill_cls is None:
                continue  # 已在 _check_unknown_skills 中处理
            
            spec = skill_cls.spec
            if spec.input_model is None:
                continue  # 无输入模型，跳过
            
            # 获取 required fields
            try:
                schema = spec.input_model.model_json_schema()
                required_fields = schema.get("required", [])
            except Exception as e:
                logger.warning(f"Failed to get schema for {step.skill_name}: {e}")
                continue
            
            # 检查必需参数是否都存在且非空
            missing_fields = []
            for field in required_fields:
                value = step.params.get(field)
                if value is None or value == "":
                    missing_fields.append(field)
            
            if missing_fields:
                # 生成友好的提示
                hint = self._generate_missing_param_hint(step.skill_name, missing_fields)
                
                # 记录统计
                for field in missing_fields:
                    self._stats["missing_fields"][field] = \
                        self._stats["missing_fields"].get(field, 0) + 1
                
                return ValidationResult(
                    is_valid=False,
                    error_type=ValidationError.MISSING_REQUIRED_PARAMS,
                    detail=f"Step {step.id} ({step.skill_name}) missing required params: {missing_fields}",
                    failed_step_id=step.id,
                    hint=hint
                )
        
        return ValidationResult(is_valid=True)
    
    def _check_type_constraints(
        self,
        steps: List[Step],
        subtask_type: SubTaskType
    ) -> ValidationResult:
        """
        检查 SubTaskType 白名单约束
        
        每个 subtask_type 只允许使用特定的技能集合。
        """
        from app.avatar.planner.models.types import get_policy
        
        policy = get_policy(subtask_type)
        
        # 如果策略定义了 allowed_skills（白名单）
        if policy.allowed_skills is not None:
            for step in steps:
                if step.skill_name not in policy.allowed_skills:
                    # 检查是否在黑名单中
                    if step.skill_name in policy.forbidden_skills:
                        hint = f"技能 {step.skill_name} 不允许用于 {subtask_type.value} 类型的任务"
                    else:
                        allowed_list = ", ".join(sorted(list(policy.allowed_skills)[:10]))
                        hint = f"{subtask_type.value} 类型的任务只能使用这些技能: {allowed_list}"
                    
                    # 记录统计
                    self._stats["blocked_skills"][step.skill_name] = \
                        self._stats["blocked_skills"].get(step.skill_name, 0) + 1
                    
                    return ValidationResult(
                        is_valid=False,
                        error_type=ValidationError.FORBIDDEN_SKILL,
                        detail=f"Skill {step.skill_name} not allowed for subtask_type={subtask_type.value}",
                        failed_step_id=step.id,
                        hint=hint
                    )
        
        # 如果只定义了黑名单
        elif policy.forbidden_skills:
            for step in steps:
                if step.skill_name in policy.forbidden_skills:
                    self._stats["blocked_skills"][step.skill_name] = \
                        self._stats["blocked_skills"].get(step.skill_name, 0) + 1
                    
                    return ValidationResult(
                        is_valid=False,
                        error_type=ValidationError.FORBIDDEN_SKILL,
                        detail=f"Skill {step.skill_name} is forbidden for subtask_type={subtask_type.value}",
                        failed_step_id=step.id,
                        hint=f"技能 {step.skill_name} 不允许用于 {subtask_type.value} 类型的任务"
                    )
        
        return ValidationResult(is_valid=True)
    
    # ========== 辅助方法 ========== #
    
    def _generate_missing_param_hint(
        self,
        skill_name: str,
        missing_fields: List[str]
    ) -> str:
        """
        生成友好的缺参提示（给 LLM 用于 replan）
        
        Args:
            skill_name: 技能名称
            missing_fields: 缺失的字段列表
        
        Returns:
            友好的提示文本
        """
        field_str = ", ".join(missing_fields)
        
        # 特殊技能的友好提示
        if skill_name == "system.open_path":
            return "system.open_path 必须提供 abs_path 或 relative_path 参数"
        elif skill_name.startswith("file."):
            return f"{skill_name} 需要提供这些参数: {field_str}（请确保包含文件路径和内容）"
        elif skill_name.startswith("llm."):
            return f"{skill_name} 需要提供 prompt 参数"
        else:
            return f"{skill_name} 缺少必需参数: {field_str}"
    
    def _record_block(self, result: ValidationResult, task_id: Optional[str] = None):
        """记录拦截统计"""
        self._stats["validate_block"] += 1
        
        if result.error_type:
            error_key = result.error_type.value
            self._stats["blocked_reasons"][error_key] = \
                self._stats["blocked_reasons"].get(error_key, 0) + 1
        
        logger.warning(
            f"🚫 PlanValidator BLOCK: {result.error_type.value if result.error_type else 'unknown'} "
            f"(task={task_id}, step={result.failed_step_id})\n"
            f"  Detail: {result.detail}\n"
            f"  Hint: {result.hint}"
        )
    
    # ========== 统计信息 ========== #
    
    @classmethod
    def get_stats(cls) -> Dict[str, Any]:
        """获取全局统计信息（可观测性）"""
        total = cls._stats["validate_pass"] + cls._stats["validate_block"]
        block_rate = cls._stats["validate_block"] / total if total > 0 else 0.0
        
        # Top blocked skills
        blocked_skills_top = sorted(
            cls._stats["blocked_skills"].items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        # Top missing fields
        missing_fields_top = sorted(
            cls._stats["missing_fields"].items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        return {
            "validate_pass": cls._stats["validate_pass"],
            "validate_block": cls._stats["validate_block"],
            "block_rate": block_rate,
            "blocked_reasons": cls._stats["blocked_reasons"],
            "blocked_skills_top": dict(blocked_skills_top),
            "missing_fields_top": dict(missing_fields_top)
        }
    
    @classmethod
    def reset_stats(cls):
        """重置统计（测试用）"""
        cls._stats = {
            "validate_pass": 0,
            "validate_block": 0,
            "blocked_reasons": {},
            "blocked_skills": {},
            "missing_fields": {}
        }


# ============================================================================
# 全局单例
# ============================================================================

_global_validator: Optional[PlanValidator] = None


def get_plan_validator() -> PlanValidator:
    """
    获取全局 PlanValidator 实例
    
    Returns:
        PlanValidator 实例
    """
    global _global_validator
    
    if _global_validator is None:
        from app.avatar.skills.registry import skill_registry
        _global_validator = PlanValidator(skill_registry)
    
    return _global_validator
