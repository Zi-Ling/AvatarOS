# app/avatar/learning/skills/skill_stats.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from ..base import LearningContext, LearningExample, LearningModule, LearningResult


@dataclass
class SkillStat:
    """某个 skill 的统计数据。"""

    name: str
    total: int = 0
    success: int = 0
    failed: int = 0
    last_error: Optional[str] = None

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.success / self.total


class SkillStatsLearner(LearningModule):
    """
    统计每个技能的使用/失败情况：
    - 依赖 LearningManager.on_skill_event(...) 提供的样本
    - 只关心 example.kind == "skill_event"
    - 适合作为“技能质量仪表盘”的数据源
    """

    name = "skill_stats"
    description = "Collects usage/failure statistics for skills."

    def __init__(self) -> None:
        # skill_name -> SkillStat
        self._stats: Dict[str, SkillStat] = {}

    # 对外可以获取快照（调试/前端展示用）
    @property
    def stats_snapshot(self) -> Dict[str, SkillStat]:
        return dict(self._stats)

    def learn(
        self,
        example: LearningExample,
        *,
        ctx: LearningContext,
    ) -> LearningResult:
        # 只关心技能事件
        if example.kind != "skill_event":
            return LearningResult(success=True, message="ignored_non_skill_event")

        data = example.input_data if isinstance(example.input_data, dict) else {}
        skill_name = data.get("skill_name")
        status = data.get("status")
        detail = data.get("detail") or ""

        if not skill_name:
            return LearningResult(success=False, message="missing_skill_name")

        stat = self._stats.get(skill_name)
        if not stat:
            stat = SkillStat(name=skill_name)
            self._stats[skill_name] = stat

        stat.total += 1
        if status == "success":
            stat.success += 1
        else:
            stat.failed += 1
            stat.last_error = detail or stat.last_error
        
        # === 新增：保存到 Knowledge Memory ===
        if ctx.memory is not None:
            try:
                # 保存技能统计到 Knowledge Memory
                ctx.memory.set_knowledge(
                    f"skill_stats:{skill_name}",
                    {
                        "skill_name": skill_name,
                        "total": stat.total,
                        "success": stat.success,
                        "failed": stat.failed,
                        "success_rate": stat.success_rate,
                        "last_error": stat.last_error,
                    }
                )
            except Exception as mem_err:
                # 忽略保存错误，不影响主流程
                pass
        # =====================================

        return LearningResult(
            success=True,
            message="skill_event_recorded",
            data={
                "skill_name": skill_name,
                "total": stat.total,
                "success": stat.success,
                "failed": stat.failed,
                "success_rate": stat.success_rate,
            },
        )
