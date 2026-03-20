"""
outcome_classifier.py — OutcomeRecord 分类逻辑

根据子目标状态判定 success/partial/failed/blocked/unsafe。
failed 时必须指定 FailureCategory，decision_basis 非空。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.avatar.evolution.models import (
    FailureCategory,
    OutcomeRecord,
    OutcomeStatus,
)

logger = logging.getLogger(__name__)


@dataclass
class SubGoalResult:
    """子目标执行结果。"""
    name: str
    satisfied: bool
    blocking: bool = True  # 是否为阻塞性子目标
    safety_blocked: bool = False  # 是否被安全策略拦截
    env_blocked: bool = False  # 是否因外部依赖不可用
    failure_hint: Optional[str] = None  # 失败原因提示


class OutcomeClassifier:
    """
    任务结果分类器。
    根据子目标状态判定 OutcomeStatus 和 FailureCategory。
    """

    # Controller verdict → OutcomeStatus mapping
    _VERDICT_MAP: Dict[str, OutcomeStatus] = {
        "success": OutcomeStatus.SUCCESS,
        "uncertain_success": OutcomeStatus.SUCCESS,
        "partial_success": OutcomeStatus.PARTIAL,
        "failed": OutcomeStatus.FAILED,
        "cancelled": OutcomeStatus.FAILED,
        "uncertain_terminal": OutcomeStatus.FAILED,
    }

    def classify(
        self,
        trace_id: str,
        task_id: str,
        sub_goals: List[SubGoalResult],
        decision_basis: str = "",
        controller_verdict: Optional[str] = None,
    ) -> OutcomeRecord:
        """
        根据子目标结果列表分类任务结果。

        当 controller_verdict 存在时，以其为 ground truth 确定 OutcomeStatus，
        sub_goals 仅用于 failure_category 分析和 summary 生成。
        这避免了 _node_covers 启发式匹配失败导致的终态语义分裂。
        """
        if controller_verdict and controller_verdict in self._VERDICT_MAP:
            status = self._VERDICT_MAP[controller_verdict]
            # Safety/env blocks override controller verdict (defense-in-depth)
            if any(sg.safety_blocked for sg in sub_goals):
                status = OutcomeStatus.UNSAFE
            elif any(sg.env_blocked for sg in sub_goals):
                status = OutcomeStatus.BLOCKED
        else:
            status = self._determine_status(sub_goals)
        failure_category = None

        if status == OutcomeStatus.FAILED:
            failure_category = self._determine_failure_category(sub_goals)

        # decision_basis 必须非空
        if not decision_basis:
            decision_basis = self._auto_decision_basis(sub_goals, status)

        return OutcomeRecord(
            outcome_id=str(uuid.uuid4()),
            trace_id=trace_id,
            task_id=task_id,
            status=status,
            failure_category=failure_category,
            summary=self._build_summary(sub_goals, status),
            decision_basis=decision_basis,
            timestamp=datetime.now(timezone.utc),
        )

    def _determine_status(self, sub_goals: List[SubGoalResult]) -> OutcomeStatus:
        """根据子目标状态判定 OutcomeStatus。"""
        if not sub_goals:
            return OutcomeStatus.FAILED

        # 安全策略拦截优先
        if any(sg.safety_blocked for sg in sub_goals):
            return OutcomeStatus.UNSAFE

        # 外部依赖不可用
        if any(sg.env_blocked for sg in sub_goals):
            return OutcomeStatus.BLOCKED

        blocking_goals = [sg for sg in sub_goals if sg.blocking]
        non_blocking_goals = [sg for sg in sub_goals if not sg.blocking]

        # 所有阻塞性子目标满足
        all_blocking_satisfied = all(sg.satisfied for sg in blocking_goals)

        if all_blocking_satisfied:
            # 检查非阻塞性子目标
            all_non_blocking_satisfied = all(sg.satisfied for sg in non_blocking_goals)
            if all_non_blocking_satisfied or not non_blocking_goals:
                return OutcomeStatus.SUCCESS
            else:
                return OutcomeStatus.PARTIAL
        else:
            # 部分阻塞性子目标满足
            any_satisfied = any(sg.satisfied for sg in sub_goals)
            if any_satisfied:
                return OutcomeStatus.PARTIAL
            return OutcomeStatus.FAILED

    def _determine_failure_category(self, sub_goals: List[SubGoalResult]) -> FailureCategory:
        """根据失败子目标的 failure_hint 推断 FailureCategory。"""
        hints = [sg.failure_hint or "" for sg in sub_goals if not sg.satisfied]
        combined = " ".join(hints).lower()

        if "goal" in combined or "misunderstand" in combined or "wrong goal" in combined:
            return FailureCategory.GOAL_MISUNDERSTANDING
        if "wrong tool" in combined or "tool selection" in combined:
            return FailureCategory.WRONG_TOOL
        if "parameter" in combined or "argument" in combined or "bad param" in combined:
            return FailureCategory.BAD_PARAMETER
        if "env" in combined or "environment" in combined or "dependency" in combined:
            return FailureCategory.ENV_ISSUE
        if "policy" in combined or "permission" in combined or "blocked" in combined:
            return FailureCategory.POLICY_BLOCK
        if "verif" in combined or "assert" in combined or "test" in combined:
            return FailureCategory.VERIFICATION_FAIL

        return FailureCategory.VERIFICATION_FAIL  # 默认

    def _auto_decision_basis(self, sub_goals: List[SubGoalResult], status: OutcomeStatus) -> str:
        """自动生成 decision_basis。"""
        total = len(sub_goals)
        satisfied = sum(1 for sg in sub_goals if sg.satisfied)
        return f"auto_classified: {satisfied}/{total} sub_goals satisfied, status={status.value}"

    def _build_summary(self, sub_goals: List[SubGoalResult], status: OutcomeStatus) -> str:
        """构建结果摘要。"""
        failed_names = [sg.name for sg in sub_goals if not sg.satisfied]
        if failed_names:
            return f"status={status.value}, failed_sub_goals={failed_names}"
        return f"status={status.value}, all sub_goals satisfied"
