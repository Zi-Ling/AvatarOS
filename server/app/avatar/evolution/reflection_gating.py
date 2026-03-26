"""
reflection_gating.py — 反思触发门控

仅在高信息增益场景下触发反思：失败、成本异常、异常恢复、新任务类型。
维护每种任务类型的成本基线统计。
"""

from __future__ import annotations

import json
import logging
import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlmodel import Session

from app.avatar.evolution.config import EvolutionConfig
from app.avatar.evolution.models import (
    CostBaseline,
    CostBaselineDB,
    CostTelemetry,
    ExecutionTrace,
    FailureCategory,
    OutcomeRecord,
    OutcomeStatus,
)

logger = logging.getLogger(__name__)


class ReflectionGating:
    """
    反思触发门控。
    维护每种任务类型的成本基线统计，判断是否触发反思。
    """

    def __init__(self, config: EvolutionConfig, db_engine: Any = None) -> None:
        self._config = config
        self._engine = db_engine
        # 内存缓存
        self._baselines: Dict[str, CostBaseline] = {}

    def resolve_task_type(self, trace: ExecutionTrace) -> str:
        """
        解析稳定的 task_type。
        优先使用工作流标签（workflow label），其次使用 skill domain 分类。
        确保同类任务不会被误判为新类型。
        """
        # task_type 已在 trace 中设置，直接使用
        if trace.task_type:
            return trace.task_type

        # 从 steps 中推断 skill domain
        if trace.steps:
            skill_names = [s.skill_name for s in trace.steps if s.skill_name]
            if skill_names:
                # 使用最常见的 skill 作为 task_type
                from collections import Counter
                most_common = Counter(skill_names).most_common(1)
                if most_common:
                    return f"skill:{most_common[0][0]}"

        return "unknown"

    def should_reflect(
        self,
        trace: ExecutionTrace,
        outcome: OutcomeRecord,
        cost: CostTelemetry,
    ) -> bool:
        """
        评估是否触发反思。
        触发条件：失败 / 成本异常 / 异常恢复 / 新任务类型。
        正常成功且成本正常且类型已知 → 跳过反思，仅更新基线。

        HARDENED: 增加前置硬条件检查。只有当终态一致、证据链完整时
        才允许生成 candidate，否则只记录 defect_trace，避免给学习层灌噪音。
        """
        task_type = self.resolve_task_type(trace)

        # ── Hard pre-conditions: skip reflection if evidence is unreliable ──
        # (a) Terminal state consistency: outcome status must not contradict
        #     the step-level evidence.
        if trace.steps:
            all_steps_success = all(s.status == "success" for s in trace.steps)
            any_step_success = any(s.status == "success" for s in trace.steps)
            if outcome.status == OutcomeStatus.FAILED and all_steps_success:
                # All steps succeeded but outcome is FAILED — state aggregation bug.
                # Reflection from this trace would learn wrong lessons.
                logger.info(
                    "[ReflectionGating] HARD SKIP: all steps succeeded but "
                    "outcome=FAILED — state aggregation inconsistency, type=%s",
                    task_type,
                )
                self.update_baseline(task_type, cost)
                return False
            if outcome.status == OutcomeStatus.SUCCESS and not any_step_success:
                # No steps succeeded but outcome is SUCCESS — impossible.
                logger.info(
                    "[ReflectionGating] HARD SKIP: no steps succeeded but "
                    "outcome=SUCCESS — evidence chain broken, type=%s",
                    task_type,
                )
                self.update_baseline(task_type, cost)
                return False

        # (b) Empty trace: no steps at all — nothing to learn from.
        if not trace.steps:
            logger.info(
                "[ReflectionGating] HARD SKIP: empty trace (no steps), type=%s",
                task_type,
            )
            self.update_baseline(task_type, cost)
            return False

        # (c) Error classification stability: if failure_category is
        #     None (unclassified), the error signal is too noisy.
        if outcome.status == OutcomeStatus.FAILED:
            _fc = outcome.failure_category
            if _fc is None:
                logger.info(
                    "[ReflectionGating] HARD SKIP: failed with unclassified "
                    "error — too noisy for reflection, type=%s",
                    task_type,
                )
                self.update_baseline(task_type, cost)
                return False

        # ── Original gating logic ───────────────────────────────────────

        # 条件 1：任务失败
        if outcome.status == OutcomeStatus.FAILED:
            # P2 filter: 如果所有执行步骤都 SUCCESS 但最终 FAILED，
            # 说明是验证基础设施 bug（如路径映射错误），不是策略失败。
            # 跳过反思，避免学到错误的 "教训"。
            if self._is_infra_verification_failure(trace, outcome):
                logger.info(
                    f"[ReflectionGating] skip: infra verification failure "
                    f"(all steps succeeded but verification failed), type={task_type}"
                )
                self.update_baseline(task_type, cost)
                return False
            logger.info(f"[ReflectionGating] trigger: failed task, type={task_type}")
            self.update_baseline(task_type, cost)
            return True

        # 条件 2：成本异常（超过同类任务中位数 × multiplier）
        baseline = self.get_baseline(task_type)
        if baseline and baseline.median_tokens > 0:
            threshold = baseline.median_tokens * self._config.cost_anomaly_multiplier
            if cost.total_tokens > threshold:
                logger.info(
                    f"[ReflectionGating] trigger: cost anomaly, "
                    f"tokens={cost.total_tokens} > threshold={threshold}"
                )
                self.update_baseline(task_type, cost)
                return True

        # 条件 3：异常恢复（从失败恢复为成功）
        if self._is_recovery(trace):
            logger.info(f"[ReflectionGating] trigger: recovery detected")
            self.update_baseline(task_type, cost)
            return True

        # 条件 4：新任务类型 — 仅建立 baseline，不触发反思
        # 走到这里 outcome 一定不是 FAILED（条件 1 已拦截），所以新任务类型
        # 到达此处必然是成功的。成功的新任务没有可学习的教训，只需建立 baseline。
        # 避免浪费两次 LLM 调用（小模型 + 大模型）产出 confidence=0 的无用候选。
        if not baseline or baseline.sample_count == 0:
            logger.info(
                f"[ReflectionGating] skip: new task type={task_type} "
                f"succeeded — baseline only"
            )
            self.update_baseline(task_type, cost)
            return False

        # 正常成功 → 跳过反思，仅更新基线
        self.update_baseline(task_type, cost)
        return False

    def update_baseline(self, task_type: str, cost: CostTelemetry) -> None:
        """更新任务类型的成本基线统计（轻量级，不调用 ReflectionEngine）。"""
        baseline = self._baselines.get(task_type)
        if not baseline:
            baseline = CostBaseline(task_type=task_type)
            self._baselines[task_type] = baseline

        baseline.token_values.append(cost.total_tokens)
        # 保留最近 N 个样本
        max_samples = self._config.cost_baseline_max_samples
        if len(baseline.token_values) > max_samples:
            baseline.token_values = baseline.token_values[-max_samples:]

        baseline.sample_count = len(baseline.token_values)
        baseline.median_tokens = float(statistics.median(baseline.token_values))
        baseline.mean_tokens = float(statistics.mean(baseline.token_values))
        baseline.last_updated = datetime.now(timezone.utc)

        # 持久化
        self._persist_baseline(baseline)

    def get_baseline(self, task_type: str) -> Optional[CostBaseline]:
        """获取任务类型的成本基线。"""
        if task_type in self._baselines:
            return self._baselines[task_type]
        # 从数据库加载
        return self._load_baseline(task_type)

    def _is_recovery(self, trace: ExecutionTrace) -> bool:
        """检测异常恢复：步骤中有失败后又成功的模式。"""
        if not trace.steps:
            return False
        saw_failure = False
        for step in trace.steps:
            if step.status == "failed":
                saw_failure = True
            elif step.status == "success" and saw_failure:
                return True
        return False

    def _is_infra_verification_failure(
        self,
        trace: ExecutionTrace,
        outcome: OutcomeRecord,
    ) -> bool:
        """
        检测基础设施验证失败：所有执行步骤都成功，但任务因 repair_exhausted 失败。
        这通常是路径映射等基础设施 bug 导致验证器误判，不应触发反思学习。
        """
        if outcome.status != OutcomeStatus.FAILED:
            return False
        # 检查是否 repair_exhausted
        is_repair_exhausted = (
            outcome.failure_category == FailureCategory.VERIFICATION_FAIL
            or "repair_exhausted" in (outcome.summary or "")
        )
        if not is_repair_exhausted:
            return False
        # 检查所有执行步骤是否都成功
        if not trace.steps:
            return False
        all_success = all(s.status == "success" for s in trace.steps)
        return all_success

    def _persist_baseline(self, baseline: CostBaseline) -> None:
        """持久化成本基线到数据库。"""
        if not self._engine:
            return
        try:
            with Session(self._engine) as session:
                existing = session.get(CostBaselineDB, baseline.task_type)
                if existing:
                    existing.sample_count = baseline.sample_count
                    existing.median_tokens = baseline.median_tokens
                    existing.mean_tokens = baseline.mean_tokens
                    existing.token_values = json.dumps(baseline.token_values)
                    existing.last_updated = baseline.last_updated
                    session.add(existing)
                else:
                    db_obj = CostBaselineDB(
                        task_type=baseline.task_type,
                        sample_count=baseline.sample_count,
                        median_tokens=baseline.median_tokens,
                        mean_tokens=baseline.mean_tokens,
                        token_values=json.dumps(baseline.token_values),
                        last_updated=baseline.last_updated,
                    )
                    session.add(db_obj)
                session.commit()
        except Exception as exc:
            logger.warning(f"[ReflectionGating] persist baseline failed: {exc}")

    def _load_baseline(self, task_type: str) -> Optional[CostBaseline]:
        """从数据库加载成本基线。"""
        if not self._engine:
            return None
        try:
            with Session(self._engine) as session:
                db_obj = session.get(CostBaselineDB, task_type)
                if not db_obj:
                    return None
                baseline = CostBaseline(
                    task_type=db_obj.task_type,
                    sample_count=db_obj.sample_count,
                    median_tokens=db_obj.median_tokens,
                    mean_tokens=db_obj.mean_tokens,
                    token_values=json.loads(db_obj.token_values) if db_obj.token_values else [],
                    last_updated=db_obj.last_updated,
                )
                self._baselines[task_type] = baseline
                return baseline
        except Exception as exc:
            logger.warning(f"[ReflectionGating] load baseline failed: {exc}")
            return None
