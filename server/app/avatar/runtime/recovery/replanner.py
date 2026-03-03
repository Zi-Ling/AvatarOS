# app/avatar/runtime/recovery/replanner.py
"""
重规划器 - 从 loop.py 提取（改进版）

目标：
- 只有"真正生成了可执行的新计划"才算 replan 成功
- 如果 planner 内部走 fallback（llm.fallback），replan 必须判失败
- 避免 "planner 没 raise 但其实失败了" 的误判
- 增加 LLM API 故障的容错处理
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any, Optional, TYPE_CHECKING, Tuple
from enum import Enum

if TYPE_CHECKING:
    from app.avatar.planner.base import TaskPlanner
    from app.avatar.planner.models import Task, Step

logger = logging.getLogger(__name__)


class ReplanFailureReason(Enum):
    """Replan 失败原因分类"""
    MAX_ATTEMPTS = "max_attempts_reached"
    NO_CHANGE = "plan_unchanged"
    FALLBACK = "contains_fallback"
    LLM_API_ERROR = "llm_api_error"
    UNKNOWN_ERROR = "unknown_error"


class Replanner:
    """
    重规划器（v2 - 增强容错）

    当任务执行失败时，重新生成执行计划
    
    Features:
    - 区分 LLM API 故障和逻辑失败
    - 对 LLM API 故障进行重试
    - 返回详细的失败原因
    """

    # 如果你有多个兜底技能，把它们都加进来
    FALLBACK_SKILLS = {"llm.fallback"}
    
    # LLM API 错误关键词（用于识别外部故障）
    LLM_API_ERROR_KEYWORDS = [
        "HTTPStatusError", "ConnectionError", "TimeoutError",
        "400 Bad Request", "401 Unauthorized", "429 Too Many Requests",
        "500 Internal Server Error", "503 Service Unavailable",
        "api.deepseek.com", "api.openai.com", "api.anthropic.com"
    ]

    def __init__(
        self,
        planner: TaskPlanner,
        max_replan_attempts: int = 3,
        llm_retry_attempts: int = 2,  # 对 LLM API 故障的重试次数
        llm_retry_delay: float = 1.0,  # 重试延迟（秒）
    ):
        self.planner = planner
        self.max_replan_attempts = max_replan_attempts
        self.llm_retry_attempts = llm_retry_attempts
        self.llm_retry_delay = llm_retry_delay

    def _get_task_signature(self, task: "Task") -> str:
        """
        用于判断 replan 前后 plan 是否真的变化（包含 params 摘要）
        
        修复问题4: 现在 signature 包含 params 的 hash，可以检测参数变化
        """
        steps = getattr(task, "steps", None) or []
        parts = []
        for s in steps:
            # 兼容 skill / skill_name
            skill = getattr(s, "skill", None) or getattr(s, "skill_name", None) or ""
            sid = getattr(s, "id", None) or ""
            
            # 获取 params 的摘要（用 hash 避免签名过长）
            params = getattr(s, "params", None) or {}
            try:
                params_json = json.dumps(params, sort_keys=True, ensure_ascii=False)
                params_hash = hashlib.md5(params_json.encode()).hexdigest()[:8]
            except Exception:
                params_hash = "invalid"
            
            parts.append(f"{sid}:{skill}:{params_hash}")
        return "|".join(parts)

    def _plan_contains_fallback(self, task: "Task") -> bool:
        """检查计划是否包含 fallback skill"""
        steps = getattr(task, "steps", None) or []
        for s in steps:
            skill = getattr(s, "skill", None) or getattr(s, "skill_name", None)
            if skill in self.FALLBACK_SKILLS:
                return True
        return False
    
    def _is_llm_api_error(self, error_msg: str) -> bool:
        """判断错误是否为 LLM API 故障"""
        if not error_msg:
            return False
        return any(keyword in error_msg for keyword in self.LLM_API_ERROR_KEYWORDS)

    async def replan(
        self,
        task: "Task",
        failed_step: Optional["Step"],
        env_context: dict,
    ) -> bool:
        """
        重新规划任务
        
        Args:
            task: 要重规划的任务
            failed_step: 失败的步骤（可能为 None）
            env_context: 环境上下文
        
        Returns:
            True: Replan 成功
            False: Replan 失败
        """
        # 修复问题2: 每次进入 replan 就计数（attempt-level），不管成功失败
        replan_count = getattr(task, "_replan_count", 0)
        setattr(task, "_replan_count", replan_count + 1)
        current_attempt = replan_count + 1
        
        # 初始化成功计数
        if not hasattr(task, "_replan_success"):
            setattr(task, "_replan_success", 0)
        
        if current_attempt > self.max_replan_attempts:
            logger.warning(f"[Replanner] Max replan attempts ({self.max_replan_attempts}) reached")
            setattr(task, "_last_replan_error_kind", ReplanFailureReason.MAX_ATTEMPTS)
            setattr(task, "_last_replan_error_msg", f"Reached max attempts: {self.max_replan_attempts}")
            return False

        # replan 前 plan 签名（用于判断是否真的变化）
        before_sig = self._get_task_signature(task)
        
        # 修复问题1: 不再使用 failed_step.result.error 来判断 API 故障
        # 只用作 planner 的上下文，不用于判断是否重试
        error_msg = failed_step.result.error if (failed_step and getattr(failed_step, "result", None)) else "Unknown error"
        
        logger.info(f"[Replanner] Attempting replan #{current_attempt}/{self.max_replan_attempts}")

        # 修复问题1: 默认不进行 API 重试，只有在 Exception 中检测到 API 错误才重试
        retry_count = 0
        
        # 修复问题1、3、5: 只在 Exception 中检测 API 错误并重试
        for attempt in range(self.llm_retry_attempts + 1):
            if attempt > 0:
                delay = self.llm_retry_delay * (2 ** (attempt - 1))  # 指数退避
                logger.info(f"[Replanner] LLM API error detected, retrying in {delay:.1f}s... (attempt {attempt + 1}/{self.llm_retry_attempts + 1})")
                await asyncio.sleep(delay)

            try:
                # 调用 planner 的 re_plan
                ret = await self.planner.re_plan(task, failed_step, error_msg, env_context)

                # 修复问题3: ret is None 视为实现 bug，直接失败，不重试
                if ret is None:
                    logger.error(f"[Replanner] Replan returned None (implementation bug in planner)")
                    setattr(task, "_last_replan_error_kind", ReplanFailureReason.UNKNOWN_ERROR)
                    setattr(task, "_last_replan_error_msg", "Planner returned None (contract violation)")
                    return False

                # 1) 如果 planner 明确返回 False —— 逻辑失败，不重试
                if ret is False:
                    logger.warning(f"[Replanner] Replan rejected by planner (ret=False)")
                    setattr(task, "_last_replan_error_kind", ReplanFailureReason.UNKNOWN_ERROR)
                    setattr(task, "_last_replan_error_msg", "Planner explicitly rejected replan")
                    return False

                # 2) 如果 replan 后 plan 没变化 —— 判失败（避免"表面成功"）
                after_sig = self._get_task_signature(task)
                if after_sig == before_sig:
                    logger.warning("[Replanner] Replan produced no plan change (signature unchanged)")
                    setattr(task, "_last_replan_error_kind", ReplanFailureReason.NO_CHANGE)
                    setattr(task, "_last_replan_error_msg", "Plan signature unchanged after replan")
                    return False

                # 3) 如果新 plan 含 fallback —— 判失败（fallback 不算 replan 成功）
                if self._plan_contains_fallback(task):
                    logger.warning("[Replanner] Replan produced fallback plan (contains llm.fallback) -> treat as failed")
                    setattr(task, "_last_replan_error_kind", ReplanFailureReason.FALLBACK)
                    setattr(task, "_last_replan_error_msg", "Plan contains fallback skill")
                    return False

                # 只有真正成功才增加成功计数
                success_count = getattr(task, "_replan_success", 0)
                setattr(task, "_replan_success", success_count + 1)
                logger.info(f"[Replanner] ✅ Replan successful (attempt {current_attempt}, success #{success_count + 1})")
                return True

            except Exception as e:
                # 修复问题1: 只用 Exception 的 error_str 来识别 API 故障
                error_str = str(e)
                is_api_error = self._is_llm_api_error(error_str)
                
                # 保存错误信息（修复问题6）
                setattr(task, "_last_replan_error_msg", error_str)
                setattr(task, "_last_replan_provider_status", str(type(e).__name__))
                
                if is_api_error and attempt < self.llm_retry_attempts:
                    logger.warning(f"[Replanner] Replan exception (LLM API error): {e}, will retry...")
                    setattr(task, "_last_replan_error_kind", ReplanFailureReason.LLM_API_ERROR)
                    continue
                
                # 所有重试都失败或非 API 错误
                logger.error(f"[Replanner] ❌ Replan failed: {e}", exc_info=True)
                if is_api_error:
                    setattr(task, "_last_replan_error_kind", ReplanFailureReason.LLM_API_ERROR)
                else:
                    setattr(task, "_last_replan_error_kind", ReplanFailureReason.UNKNOWN_ERROR)
                return False
        
        # 所有重试都失败（API 错误）
        logger.error(f"[Replanner] ❌ Replan failed after {self.llm_retry_attempts + 1} attempts (LLM API error)")
        setattr(task, "_last_replan_error_kind", ReplanFailureReason.LLM_API_ERROR)
        return False
    
    def get_failure_reason(self, task: "Task") -> Optional[ReplanFailureReason]:
        """
        获取 replan 失败原因（用于错误报告）
        
        修复问题6: 现在从 task 中读取详细的失败原因，而不是靠猜测
        
        Note: 这是一个辅助方法，可在 replan 失败后调用以获取详细原因
        """
        # 优先返回最后一次明确记录的失败原因
        last_error_kind = getattr(task, "_last_replan_error_kind", None)
        if last_error_kind:
            return last_error_kind
        
        # 兜底：根据状态推测（向后兼容）
        replan_count = getattr(task, "_replan_count", 0)
        
        if replan_count >= self.max_replan_attempts:
            return ReplanFailureReason.MAX_ATTEMPTS
        
        if self._plan_contains_fallback(task):
            return ReplanFailureReason.FALLBACK
        
        return ReplanFailureReason.UNKNOWN_ERROR
    
    def get_failure_details(self, task: "Task") -> dict:
        """
        获取详细的失败信息（修复问题6）
        
        Returns:
            {
                "reason": ReplanFailureReason,
                "error_msg": str,
                "provider_status": str,
                "attempt_count": int,
                "success_count": int
            }
        """
        return {
            "reason": self.get_failure_reason(task),
            "error_msg": getattr(task, "_last_replan_error_msg", "Unknown"),
            "provider_status": getattr(task, "_last_replan_provider_status", "Unknown"),
            "attempt_count": getattr(task, "_replan_count", 0),
            "success_count": getattr(task, "_replan_success", 0),
        }
