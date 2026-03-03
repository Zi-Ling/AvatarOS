# app/avatar/runtime/recovery/self_corrector.py
"""
自我修复协调器
"""
from __future__ import annotations

import logging
from typing import Optional, Any

from .manager import CodeRepairManager

logger = logging.getLogger(__name__)


class SelfCorrector:
    """
    自我修复协调器
    
    负责协调代码修复流程，包括修复尝试、回滚等
    """
    
    def __init__(
        self,
        repair_manager: Optional[CodeRepairManager] = None,
        max_repair_attempts: int = 2
    ):
        """
        Args:
            repair_manager: 代码修复管理器
            max_repair_attempts: 最大修复尝试次数
        """
        self.repair_manager = repair_manager
        self.max_repair_attempts = max_repair_attempts
    
    async def attempt_correction(
        self,
        step: Any,
        error_msg: str,
        task_goal: str = ""
    ) -> bool:
        """
        尝试自我修复
        
        Args:
            step: 失败的步骤对象
            error_msg: 错误消息
            task_goal: 任务目标（用于上下文）
        
        Returns:
            是否修复成功
        """
        if not self.repair_manager:
            logger.warning("[SelfCorrector] RepairManager not available")
            return False
        
        if step.skill_name != "python.run":
            return False
        
        code = step.params.get("code", "")
        if not code:
            logger.warning("[SelfCorrector] No code to repair")
            return False
        
        repair_count = getattr(step, "_repair_count", 0)
        
        if repair_count >= self.max_repair_attempts:
            logger.warning(f"[SelfCorrector] Max repair attempts ({self.max_repair_attempts}) reached for step {step.id}")
            return False
        
        logger.info(f"[SelfCorrector] Attempting repair #{repair_count + 1} for step {step.id}")
        
        try:
            repair_result = await self.repair_manager.attempt_repair(
                step=step,
                error_msg=error_msg,
                task_goal=task_goal
            )
            
            if repair_result.success:
                step.params["code"] = repair_result.fixed_code
                logger.info(f"[SelfCorrector] ✅ Repair successful for step {step.id}")
                return True
            else:
                logger.warning(f"[SelfCorrector] ❌ Repair failed: {repair_result.error}")
                
                # 如果是最后一次尝试失败，回滚到原始代码
                if repair_count >= self.max_repair_attempts - 1:
                    first_snapshot = getattr(step, "_first_snapshot", None)
                    if first_snapshot and self.repair_manager:
                        self.repair_manager.rollback(step, first_snapshot)
                        logger.info(f"[SelfCorrector] Rolled back step {step.id} to original code")
                    
                    # 清理修复相关属性
                    if hasattr(step, "_first_snapshot"):
                        delattr(step, "_first_snapshot")
                    if hasattr(step, "_repair_count"):
                        delattr(step, "_repair_count")
                
                return False
                
        except Exception as e:
            logger.error(f"[SelfCorrector] Exception during repair: {e}")
            return False

