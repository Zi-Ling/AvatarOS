"""
pipeline.py — EvolutionPipeline 编排门面

编排 TraceCollector → OutcomeClassifier → CostTelemetry → ReflectionGating
→ ReflectionEngine → LearningStore 的完整流程。

支持阶段一降级运行（无 ReflectionEngine 时仅采集 trace）。
任一阶段失败时安全终止，不影响已有 ActiveSet。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from app.avatar.evolution.audit_logger import EvolutionAuditLogger
from app.avatar.evolution.config import EvolutionConfig
from app.avatar.evolution.cost_telemetry import CostTelemetryAggregator
from app.avatar.evolution.learning_store import LearningStore
from app.avatar.evolution.models import (
    CandidateStatus,
    CostTelemetry,
    ExecutionTrace,
    LearningCandidate,
    OutcomeRecord,
    OutcomeStatus,
    PromotionTier,
    ReflectionOutput,
    ValidationResult,
)
from app.avatar.evolution.outcome_classifier import OutcomeClassifier, SubGoalResult
from app.avatar.evolution.promotion_manager import PromotionManager
from app.avatar.evolution.reflection_engine import ReflectionEngine
from app.avatar.evolution.reflection_gating import ReflectionGating
from app.avatar.evolution.rollback_manager import RollbackManager
from app.avatar.evolution.trace_collector import TraceCollector
from app.avatar.evolution.validation_gate import ValidationGate

logger = logging.getLogger(__name__)


class PipelineResult:
    """Pipeline 单次执行结果。"""

    __slots__ = (
        "trace", "outcome", "cost", "should_reflect",
        "reflection", "candidates", "error", "stage_reached",
        "validation_results", "promoted_candidates",
    )

    def __init__(self) -> None:
        self.trace: Optional[ExecutionTrace] = None
        self.outcome: Optional[OutcomeRecord] = None
        self.cost: Optional[CostTelemetry] = None
        self.should_reflect: bool = False
        self.reflection: Optional[ReflectionOutput] = None
        self.candidates: List[LearningCandidate] = []
        self.error: Optional[str] = None
        self.stage_reached: str = "init"
        # Phase 3 fields
        self.validation_results: List[ValidationResult] = []
        self.promoted_candidates: List[LearningCandidate] = []


class EvolutionPipeline:
    """
    演化 Pipeline 编排门面。
    作为 LearningManager 的扩展入口，编排完整的 Trace→Reflect→Store 流程。
    """

    def __init__(
        self,
        trace_collector: TraceCollector,
        outcome_classifier: OutcomeClassifier,
        cost_aggregator: CostTelemetryAggregator,
        reflection_gating: ReflectionGating,
        config: Optional[EvolutionConfig] = None,
        reflection_engine: Optional[ReflectionEngine] = None,
        learning_store: Optional[LearningStore] = None,
        audit_logger: Optional[EvolutionAuditLogger] = None,
        validation_gate: Optional[ValidationGate] = None,
        promotion_manager: Optional[PromotionManager] = None,
        rollback_manager: Optional[RollbackManager] = None,
    ) -> None:
        self._trace_collector = trace_collector
        self._outcome_classifier = outcome_classifier
        self._cost_aggregator = cost_aggregator
        self._reflection_gating = reflection_gating
        self._config = config or EvolutionConfig()
        # Phase 2 components (optional)
        self._reflection_engine = reflection_engine
        self._learning_store = learning_store
        self._audit_logger = audit_logger
        # Phase 3 components (optional)
        self._validation_gate = validation_gate
        self._promotion_manager = promotion_manager
        self._rollback_manager = rollback_manager

    @property
    def phase(self) -> int:
        """当前运行阶段：1=仅 trace 采集，2=含反思和候选生成，3=含验证和晋升。"""
        if (self._reflection_engine and self._learning_store
                and self._validation_gate and self._promotion_manager):
            return 3
        if self._reflection_engine and self._learning_store:
            return 2
        return 1

    # ------------------------------------------------------------------
    # on_task_finished_v2 — 在线模式入口
    # ------------------------------------------------------------------

    async def on_task_finished_v2(
        self,
        *,
        task_id: str,
        session_id: str,
        goal: str,
        task_type: str,
        sub_goals: List[SubGoalResult],
        decision_basis: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> PipelineResult:
        """
        任务完成后的演化 pipeline 入口（在线模式）。

        流程：
        1. TraceCollector.finalize_trace → 获取完整 trace
        2. OutcomeClassifier.classify → 生成 OutcomeRecord
        3. CostTelemetryAggregator.aggregate → 生成 CostTelemetry
        4. ReflectionGating.should_reflect → 判断是否触发反思
        5. ReflectionEngine.reflect → 结构化反思（阶段二）
        6. LearningStore.create_from_rule + save → 持久化候选（阶段二）

        任一阶段失败时安全终止，不影响已有 ActiveSet。
        """
        result = PipelineResult()

        # --- Stage 1: Finalize trace ---
        try:
            trace = self._trace_collector.finalize_trace(
                self._find_trace_id(task_id)
            )
            if not trace:
                # 可能 trace 未创建（非演化任务），静默返回
                result.stage_reached = "trace_not_found"
                return result
            result.trace = trace
            result.stage_reached = "trace_finalized"
        except Exception as exc:
            logger.warning(f"[EvolutionPipeline] trace finalize failed: {exc}")
            result.error = f"trace_finalize: {exc}"
            return result

        # --- Stage 2: Classify outcome ---
        try:
            outcome = self._outcome_classifier.classify(
                trace_id=trace.trace_id,
                task_id=task_id,
                sub_goals=sub_goals,
                decision_basis=decision_basis,
            )
            self._trace_collector.record_outcome(
                trace_id=trace.trace_id,
                task_id=task_id,
                status=outcome.status,
                failure_category=outcome.failure_category,
                summary=outcome.summary,
                decision_basis=outcome.decision_basis,
            )
            result.outcome = outcome
            result.stage_reached = "outcome_classified"
        except Exception as exc:
            logger.warning(f"[EvolutionPipeline] outcome classify failed: {exc}")
            result.error = f"outcome_classify: {exc}"
            return result

        # --- Stage 3: Aggregate cost ---
        try:
            cost = self._cost_aggregator.aggregate_for_trace(
                trace_id=trace.trace_id,
                task_id=task_id,
                session_id=session_id,
                start_time=trace.start_time.timestamp() if trace.start_time else 0,
                end_time=trace.end_time.timestamp() if trace.end_time else time.time(),
            )
            self._trace_collector.record_cost(trace.trace_id, cost)
            result.cost = cost
            result.stage_reached = "cost_aggregated"
        except Exception as exc:
            logger.warning(f"[EvolutionPipeline] cost aggregate failed: {exc}")
            result.error = f"cost_aggregate: {exc}"
            return result

        # --- Stage 4: Reflection gating ---
        try:
            should = self._reflection_gating.should_reflect(trace, outcome, cost)
            result.should_reflect = should
            result.stage_reached = "gating_evaluated"
        except Exception as exc:
            logger.warning(f"[EvolutionPipeline] reflection gating failed: {exc}")
            result.error = f"reflection_gating: {exc}"
            return result

        if not should:
            return result

        # --- 阶段一降级：无 ReflectionEngine 时到此为止 ---
        if self.phase == 1:
            result.stage_reached = "phase1_complete"
            return result

        # --- Stage 5: Reflection ---
        try:
            reflection = await self._reflection_engine.reflect(trace)  # type: ignore[union-attr]
            result.reflection = reflection
            result.stage_reached = "reflected"
            if self._audit_logger:
                self._audit_logger.log_reflection(reflection, trace.trace_id)
        except Exception as exc:
            logger.warning(f"[EvolutionPipeline] reflection failed: {exc}")
            result.error = f"reflection: {exc}"
            return result

        # --- Stage 6: Create and store candidates ---
        try:
            candidates = self._create_candidates(reflection)
            result.candidates = candidates
            result.stage_reached = "candidates_stored"
        except Exception as exc:
            logger.warning(f"[EvolutionPipeline] candidate store failed: {exc}")
            result.error = f"candidate_store: {exc}"
            return result

        # --- Phase 3: Validation + Promotion (optional) ---
        if self.phase >= 3 and candidates:
            try:
                validated, promoted = self._validate_and_promote(candidates)
                result.validation_results = validated
                result.promoted_candidates = promoted
                result.stage_reached = "promoted"
            except Exception as exc:
                logger.warning(f"[EvolutionPipeline] validation/promotion failed: {exc}")
                result.error = f"validation_promotion: {exc}"
                # non-fatal: candidates are already stored
                result.stage_reached = "candidates_stored"

        return result

    # ------------------------------------------------------------------
    # on_task_finished_v2_offline — 离线批处理入口
    # ------------------------------------------------------------------

    async def on_task_finished_v2_offline(
        self,
        traces: List[ExecutionTrace],
    ) -> List[PipelineResult]:
        """
        离线学习模式入口。
        对一批已完成的 trace 执行反思和候选生成。
        不阻塞在线 TraceCollector 写入。
        """
        if not self._config.offline_mode_enabled:
            logger.info("[EvolutionPipeline] offline mode disabled, skipping")
            return []

        results: List[PipelineResult] = []
        batch_size = self._config.offline_batch_size

        for i in range(0, len(traces), batch_size):
            batch = traces[i : i + batch_size]
            for trace in batch:
                r = await self._process_offline_trace(trace)
                results.append(r)

        return results

    async def _process_offline_trace(self, trace: ExecutionTrace) -> PipelineResult:
        """处理单条离线 trace。"""
        result = PipelineResult()
        result.trace = trace
        result.stage_reached = "offline_start"

        if not trace.outcome:
            result.stage_reached = "offline_no_outcome"
            return result

        outcome = trace.outcome

        # 构造 cost（离线模式下从 trace 已有数据获取）
        cost = trace.cost_telemetry or CostTelemetry(trace_id=trace.trace_id)
        result.outcome = outcome
        result.cost = cost

        # Gating
        try:
            should = self._reflection_gating.should_reflect(trace, outcome, cost)
            result.should_reflect = should
            result.stage_reached = "offline_gating"
        except Exception as exc:
            result.error = f"offline_gating: {exc}"
            return result

        if not should or self.phase == 1:
            result.stage_reached = "offline_gating_skip"
            return result

        # Reflection
        try:
            reflection = await self._reflection_engine.reflect(trace)  # type: ignore[union-attr]
            result.reflection = reflection
            result.stage_reached = "offline_reflected"
            if self._audit_logger:
                self._audit_logger.log_reflection(reflection, trace.trace_id)
        except Exception as exc:
            result.error = f"offline_reflection: {exc}"
            return result

        # Store candidates
        try:
            candidates = self._create_candidates(reflection)
            result.candidates = candidates
            result.stage_reached = "offline_candidates_stored"
        except Exception as exc:
            result.error = f"offline_candidate_store: {exc}"
            return result

        # Phase 3: Validation + Promotion (optional)
        if self.phase >= 3 and candidates:
            try:
                validated, promoted = self._validate_and_promote(candidates)
                result.validation_results = validated
                result.promoted_candidates = promoted
                result.stage_reached = "offline_promoted"
            except Exception as exc:
                logger.warning(f"[EvolutionPipeline] offline validation/promotion failed: {exc}")
                result.stage_reached = "offline_candidates_stored"

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_trace_id(self, task_id: str) -> str:
        """从 TraceCollector 内存缓存中查找 task_id 对应的 trace_id。"""
        for tid, trace in self._trace_collector._traces.items():
            if trace.task_id == task_id:
                return tid
        return ""

    def _create_candidates(
        self, reflection: ReflectionOutput
    ) -> List[LearningCandidate]:
        """从 ReflectionOutput 的 candidate_rules 创建并持久化 LearningCandidate。"""
        candidates: List[LearningCandidate] = []
        if not self._learning_store:
            return candidates

        for rule in reflection.candidate_rules:
            candidate = self._learning_store.create_from_rule(
                rule=rule,
                source_reflection_id=reflection.reflection_id,
                evidence_links=reflection.evidence_links,
            )
            self._learning_store.save_candidate(candidate)
            candidates.append(candidate)

            if self._audit_logger:
                self._audit_logger.log_candidate_created(candidate)

        return candidates

    def _validate_and_promote(
        self, candidates: List[LearningCandidate]
    ) -> tuple:
        """
        Phase 3: validate each candidate and promote based on tier.
        Also runs opportunistic shadow expiration check.
        Returns (validation_results, promoted_candidates).
        """
        validation_results: List[ValidationResult] = []
        promoted: List[LearningCandidate] = []

        # Opportunistic shadow expiration check
        if self._promotion_manager:
            try:
                expired = self._promotion_manager.check_shadow_expirations()
                promoted.extend(expired)
            except Exception as exc:
                logger.warning(f"[EvolutionPipeline] shadow expiration check failed: {exc}")

        for candidate in candidates:
            vr = self._validation_gate.validate(candidate)  # type: ignore[union-attr]
            validation_results.append(vr)

            tier = self._validation_gate.determine_tier(candidate)  # type: ignore[union-attr]
            result = self._promotion_manager.promote(candidate, vr, tier)  # type: ignore[union-attr]

            if result.status in (CandidateStatus.ACTIVE, CandidateStatus.SHADOW):
                promoted.append(result)

            if self._audit_logger:
                self._audit_logger.log_status_change(
                    candidate_id=candidate.candidate_id,
                    from_status=CandidateStatus.DRAFT.value,
                    to_status=result.status.value,
                    reason=vr.reason,
                )

        return validation_results, promoted
