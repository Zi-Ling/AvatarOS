"""
Step Executor

Executes individual steps with retry logic, SkillGuard checking,
and execution history recording.
"""
from __future__ import annotations

import asyncio
import time
import logging
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.avatar.runtime.core import TaskContext, StepContext
    from app.avatar.skills.guard import SkillGuard

from ...models import Step, StepResult, StepStatus
from ...core.event_bus_wrapper import EventBusWrapper
from app.avatar.skills.registry import skill_registry

logger = logging.getLogger(__name__)


class StepExecutor:
    """
    步骤执行器
    
    职责：
    - 重试逻辑（指数退避）
    - SkillGuard 检查
    - Skill 调用
    - 执行历史记录
    """
    
    def __init__(self, event_bus_wrapper: Optional[EventBusWrapper] = None):
        """
        初始化步骤执行器
        
        Args:
            event_bus_wrapper: 事件总线包装器
        """
        self.event_bus = event_bus_wrapper or EventBusWrapper()
    
    async def execute(
        self,
        step: Step,
        ctx: Any,  # SkillContext
        task_ctx: Optional[TaskContext],
        step_ctx: Optional[StepContext],
        resolved_params: dict,
        *,
        skill_guard: Optional[SkillGuard] = None,
        step_index: int = 0
    ) -> None:
        """
        执行步骤（含重试逻辑）
        
        Args:
            step: 要执行的步骤
            ctx: SkillContext
            task_ctx: TaskContext（可选）
            step_ctx: StepContext（可选）
            resolved_params: 已解析的参数
            skill_guard: SkillGuard（可选）
            step_index: 步骤索引
        """
        max_attempts = step.max_retry + 1
        start_time = time.time()
        
        # 参数类型转换
        try:
            resolved_params = self._ensure_parameter_compatibility(step.skill_name, resolved_params)
        except Exception as e:
            logger.warning(f"Parameter type conversion failed for step {step.id}: {e}")

        for attempt in range(max_attempts):
            if attempt > 0:
                logger.info(f"[Retry] Step {step.id} attempt {attempt + 1}/{max_attempts}")
                # 指数退避
                delay = min(2 ** (attempt - 1), 10)
                await asyncio.sleep(delay)
            
            step.status = StepStatus.RUNNING
            step.retry = attempt
            
            # 发布开始事件
            self.event_bus.publish_step_start(
                step.id,
                step.skill_name,
                resolved_params,
                attempt + 1,
                max_attempts
            )
            
            # SkillGuard 检查
            if skill_guard:
                guard_error = self._check_skill_guard(skill_guard, step, resolved_params)
                if guard_error:
                    self._fail_step(step, guard_error)
                    return
            
            # 执行步骤
            success, error = await self._execute_skill(
                step, ctx, step_ctx, resolved_params
            )
            
            if success:
                # 成功：发布成功事件并退出
                duration = time.time() - start_time
                self._publish_success_event(step, duration)
                break
            else:
                # 失败：检查是否需要重试
                if attempt < max_attempts - 1:
                    # 还有重试机会
                    logger.warning(f"[Retry] Step {step.id} failed (attempt {attempt + 1}): {error}")
                    self.event_bus.publish_step_failed(
                        step.id,
                        error or "Execution failed",
                        will_retry=True,
                        attempt=attempt + 1,
                        max_attempts=max_attempts
                    )
                else:
                    # 最后一次尝试失败
                    logger.error(f"[Retry] Step {step.id} failed after {max_attempts} attempts: {error}")
                    self.event_bus.publish_step_failed(
                        step.id,
                        error or "Execution failed",
                        will_retry=False,
                        attempt=attempt + 1,
                        max_attempts=max_attempts
                    )
                    break
        
        # 记录执行历史
        self._record_history(
            task_ctx,
            step,
            step_index,
            resolved_params,
            time.time() - start_time
        )
    
    def _get_required_fields(self, input_model: Any) -> list:
        """获取 Pydantic 模型的 Required 字段"""
        if not hasattr(input_model, "model_fields"):
            return []
        
        required = []
        for field_name, field_info in input_model.model_fields.items():
            if field_info.is_required():
                required.append(field_name)
        
        return required
    
    def _ensure_parameter_compatibility(self, skill_name: str, params: dict) -> dict:
        """
        智能参数类型适配：
        如果 Skill 定义要求 str，但参数是 int/float，则自动转换为 str。
        """
        # 1. 获取技能定义
        skill_cls = skill_registry.get(skill_name)
        if not skill_cls or not getattr(skill_cls, "spec", None) or not skill_cls.spec.input_model:
            return params

        # 2. 遍历参数并进行必要转换
        new_params = params.copy()
        model_fields = skill_cls.spec.input_model.model_fields
        
        for name, value in new_params.items():
            if name not in model_fields:
                continue
                
            field_info = model_fields[name]
            target_type = field_info.annotation
            
            # 判断逻辑：目标是字符串，但当前值是数字
            is_target_str = target_type is str 
            
            # 扩展：支持 Optional[str] (Union[str, NoneType])
            if not is_target_str and hasattr(target_type, "__origin__"):
                 # Check if it's a Union containing str
                 args = getattr(target_type, "__args__", ())
                 if str in args:
                     is_target_str = True

            is_value_number = isinstance(value, (int, float))
            
            if is_target_str and is_value_number:
                logger.debug(f"[AutoCast] Converting param '{name}' from {type(value).__name__} to str for skill '{skill_name}'")
                new_params[name] = str(value)
                
        return new_params

    def _check_skill_guard(
        self,
        skill_guard: SkillGuard,
        step: Step,
        params: dict
    ) -> Optional[str]:
        """
        检查 SkillGuard
        
        Returns:
            错误消息（如果被拦截），否则 None
        """
        try:
            # 支持新的 validate() 接口，降级到 check()
            if hasattr(skill_guard, "validate"):
                return skill_guard.validate(step.skill_name, params)
            else:
                allowed = skill_guard.check(step.skill_name, params)
                if not allowed:
                    return "Blocked by SkillGuard (unspecified reason)"
        except Exception as e:
            return f"SkillGuard check error: {str(e)}"
        
        return None
    
    async def _execute_skill(
        self,
        step: Step,
        ctx: Any,
        step_ctx: Optional[StepContext],
        params: dict
    ) -> tuple[bool, Optional[str]]:
        """
        执行技能
        
        Returns:
            (成功标志, 错误消息)
        """
        try:
            # 调用技能
            output = await ctx.call_skill(step.skill_name, params, step_ctx=step_ctx)
            
            # 判断成功
            is_success = True
            error_msg = None
            
            if hasattr(output, "success"):
                is_success = output.success
            elif isinstance(output, dict) and "success" in output:
                is_success = output["success"]
            
            # 转换输出为字典
            if hasattr(output, "dict"):
                output = output.dict()
            
            # 提取错误消息
            if not is_success:
                if isinstance(output, dict):
                    error_msg = output.get("message") or output.get("error")
                elif hasattr(output, "message"):
                    error_msg = output.message
            
            # 更新步骤状态
            step.status = StepStatus.SUCCESS if is_success else StepStatus.FAILED
            step.result = StepResult(success=is_success, output=output, error=error_msg)
            
            # [DEBUG] 记录步骤结果保存情况
            output_summary = str(output)[:200] if output else "None"
            logger.debug(f"[StepExecutor] Step {step.id} result saved: success={is_success}, output_type={type(output).__name__}, output_preview={output_summary}")
            
            # 同步上下文
            if is_success and step_ctx:
                step_ctx.set_output(output)
            
            return is_success, error_msg
            
        except Exception as e:
            logger.error(f"Step {step.id} execution exception: {e}")
            self._fail_step(step, str(e))
            return False, str(e)
    
    def _fail_step(self, step: Step, error: str) -> None:
        """标记步骤失败"""
        step.status = StepStatus.FAILED
        step.result = StepResult(success=False, error=error)
    
    def _publish_success_event(self, step: Step, duration: float) -> None:
        """发布成功事件"""
        if not step.result or not step.result.output:
            return
        
        # 生成自然语言总结
        summary = "Execution completed"
        try:
            from ...summarizer import ResultSummarizer
            summary = ResultSummarizer.summarize(step.skill_name, step.result.output)
        except Exception as e:
            logger.warning(f"Failed to summarize step result: {e}")
        
        self.event_bus.publish_step_end(
            step.id,
            step.result.output,
            duration,
            summary
        )
        
        # 检测文件系统操作
        if isinstance(step.result.output, dict) and step.result.output.get('fs_operation'):
            self.event_bus.publish_file_operation(
                step.result.output['fs_operation'],
                step.result.output.get('fs_path', ''),
                step.result.output.get('fs_type', 'file'),
                step.id
            )
    
    def _record_history(
        self,
        task_ctx: Optional[TaskContext],
        step: Step,
        step_index: int,
        resolved_params: dict,
        duration: float
    ) -> None:
        """记录执行历史"""
        if not task_ctx:
            return
        
        try:
            from app.avatar.runtime.core.context import StepRecord
            
            # 简化输入/输出（避免过长）
            input_summary = {
                k: str(v)[:100] + "..." if isinstance(v, str) and len(v) > 100 else v
                for k, v in resolved_params.items()
            }
            
            output_summary = None
            if step.result and step.result.output:
                output_raw = step.result.output
                if isinstance(output_raw, dict):
                    output_summary = {
                        k: str(v)[:100] + "..." if isinstance(v, str) and len(v) > 100 else v
                        for k, v in output_raw.items()
                    }
                else:
                    output_summary = str(output_raw)[:200]
            
            record = StepRecord(
                step_index=step_index,
                step_id=step.id,
                skill_name=step.skill_name,
                status=step.status.name,
                inputs=input_summary,
                outputs=output_summary,
                duration_ms=duration * 1000,
                timestamp=time.time()
            )
            
            task_ctx.history.add_step(record)
            task_ctx.save_snapshot()
            
        except Exception as e:
            logger.warning(f"Failed to record execution history: {e}")
