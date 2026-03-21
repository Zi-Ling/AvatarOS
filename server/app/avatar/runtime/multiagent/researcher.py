"""ResearcherRunner — Researcher 角色 RoleRunner 实现.

唯一全新角色，仅使用只读工具。输出结构化摘要。

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from .agent_instance import TaskPacket

logger = logging.getLogger(__name__)


class ResearcherRunner:
    """Researcher 角色执行器.

    实现 RoleRunner 协议。
    execute() 方法：收集事实、约束、候选方案，输出结构化摘要。
    输出包含：facts, constraints, candidates, missing_items, conclusion。
    仅使用只读工具。
    """

    async def execute(
        self, task_packet: TaskPacket, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """执行研究任务，返回结构化摘要.

        Phase 1: 返回基础结构，实际 LLM 调用由上层集成。
        """
        goal = task_packet.goal
        logger.info(
            "[ResearcherRunner] executing research for goal: %s", goal[:100]
        )

        # Phase 1: 基础结构化输出框架
        result: Dict[str, Any] = {
            "facts": [],
            "constraints": [],
            "candidates": [],
            "missing_items": [],
            "conclusion": "",
            "metadata": {
                "goal": goal,
                "instance_id": context.get("instance_id", ""),
            },
        }
        return result
