# server/app/avatar/planner/gatekeeper.py
"""
Execution Gatekeeper — side_effects + risk_level driven routing.

Replaces the old meta.domain / meta.capabilities approach.
"""

import logging
from typing import Any, Dict

from app.avatar.skills.base import SideEffect, SkillRiskLevel
from app.avatar.skills.registry import skill_registry

logger = logging.getLogger(__name__)


class ExecutionGatekeeper:
    """
    决策是否允许通用技能（如 python.run）参与候选。

    策略：
    - 如果存在 side_effects 完全覆盖意图的专用技能，则屏蔽 python.run
    - python.run 的 risk_level 为 EXECUTE，只在没有更合适的专用技能时出场
    - 黑名单 SubTaskType 直接拦截
    """

    # python.run 在这些 subtask_type 中永远不允许出场
    _PYTHON_RUN_BLOCKED_SUBTASK_TYPES = {
        "delete_operation",
        "gui_operation",
        "schedule",
    }

    @staticmethod
    def filter_skills(intent: Any, skills: Dict[str, Any]) -> Dict[str, Any]:
        """
        过滤技能列表，移除不应该使用的通用技能。

        Args:
            intent: Intent 对象
            skills: {skill_name: description_dict}

        Returns:
            过滤后的技能字典
        """
        if "python.run" not in skills:
            return skills

        if not ExecutionGatekeeper._should_allow_python_run(intent, skills):
            result = skills.copy()
            result.pop("python.run")
            logger.info("[Gatekeeper] python.run removed from candidates")
            return result

        return skills

    @staticmethod
    def _should_allow_python_run(intent: Any, skills: Dict[str, Any]) -> bool:
        # 1. SubTaskType 黑名单
        subtask_type = ""
        if hasattr(intent, "metadata") and intent.metadata:
            subtask_type = intent.metadata.get("subtask_type", "")
        if subtask_type in ExecutionGatekeeper._PYTHON_RUN_BLOCKED_SUBTASK_TYPES:
            logger.info(f"[Gatekeeper] python.run blocked: subtask_type='{subtask_type}'")
            return False

        # 2. 如果有专用技能（risk_level < EXECUTE），优先使用专用技能
        specialized = []
        for name in skills:
            if name == "python.run":
                continue
            cls = skill_registry.get(name)
            if cls and hasattr(cls, "spec"):
                spec = cls.spec
                if spec.risk_level in (SkillRiskLevel.SAFE, SkillRiskLevel.READ, SkillRiskLevel.WRITE):
                    specialized.append(name)

        if specialized:
            logger.info(f"[Gatekeeper] python.run suppressed — specialized skills available: {specialized}")
            return False

        # 3. 没有专用技能，允许 python.run 作为兜底
        logger.info("[Gatekeeper] python.run allowed — no specialized skills available")
        return True
