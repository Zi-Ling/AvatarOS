# app/avatar/runtime/executor/local.py

"""
本地执行器

直接在主进程中执行 Skill，无隔离。
仅用于 SAFE 级别的 Skill（纯计算、无副作用）。
"""

import asyncio
import logging
from typing import Any

from .base import SkillExecutor, ExecutionStrategy
from app.avatar.skills.base import SkillRiskLevel

logger = logging.getLogger(__name__)


class LocalExecutor(SkillExecutor):
    """
    本地执行器
    
    特点：
    - 直接执行，无隔离
    - 性能最优（<1ms）
    - 仅允许 SAFE 级别 Skill
    """
    
    def __init__(self):
        super().__init__()
        self.strategy = ExecutionStrategy.LOCAL
    
    def supports(self, skill: Any) -> bool:
        """只支持 SAFE 级别的 Skill"""
        try:
            risk_level = skill.spec.meta.risk_level
            return risk_level == SkillRiskLevel.SAFE
        except Exception as e:
            logger.warning(f"[LocalExecutor] Failed to get risk_level: {e}")
            return False
    
    async def execute(self, skill: Any, input_data: Any, context: Any) -> Any:
        """
        直接执行 Skill
        
        Args:
            skill: Skill 实例
            input_data: 输入数据
            context: SkillContext
        
        Returns:
            执行结果
        """
        logger.debug(f"[LocalExecutor] Executing {skill.spec.api_name}")
        
        try:
            # 调用 Skill 的 run 方法
            result = skill.run(context, input_data)
            
            # 处理异步结果
            if asyncio.iscoroutine(result):
                result = await result
            
            logger.debug(f"[LocalExecutor] Success: {skill.spec.api_name}")
            return result
            
        except Exception as e:
            logger.error(f"[LocalExecutor] Failed: {skill.spec.api_name}, error: {e}")
            raise
