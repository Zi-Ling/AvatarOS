"""
trace_collector.py — 全链路轨迹采集器

采用 append-only 写入策略，写入失败不阻塞主任务流程。
仅从真实任务执行中采集 trace，不依赖合成数据。
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlmodel import Session

from app.avatar.evolution.config import EvolutionConfig
from app.avatar.evolution.models import (
    ArtifactSnapshot,
    ArtifactSnapshotDB,
    ContentRef,
    CostTelemetry,
    CostTelemetryDB,
    ExecutionTrace,
    ExecutionTraceDB,
    FailureCategory,
    OutcomeRecord,
    OutcomeRecordDB,
    OutcomeStatus,
    SideEffectType,
    StepRecord,
    StepRecordDB,
    ToolCallRecord,
    TraceHole,
)

logger = logging.getLogger(__name__)


class TraceCollector:
    """
    全链路轨迹采集器。
    与 StepTraceStore 复用事件记录能力，在其上层构建演化专用的结构化 trace。
    """

    def __init__(
        self,
        db_engine: Any,
        config: EvolutionConfig,
        artifact_store: Any = None,
        step_trace_store: Any = None,
    ) -> None:
        self._engine = db_engine
        self._config = config
        self._artifact_store = artifact_store
        self._step_trace_store = step_trace_store
        # In-memory trace cache for current traces
        self._traces: Dict[str, ExecutionTrace] = {}

    # ------------------------------------------------------------------
    # create_trace
    # ------------------------------------------------------------------

    def create_trace(
        self,
        task_id: str,
        session_id: str,
        goal: str,
        task_type: str,
    ) -> ExecutionTrace:
        """任务开始时创建 trace 记录。"""
        trace = ExecutionTrace(
            trace_id=str(uuid.uuid4()),
            task_id=task_id,
            session_id=session_id,
            goal=goal,
            task_type=task_type,
            start_time=datetime.now(timezone.utc),
        )
        self._traces[trace.trace_id] = trace
        self._persist_trace(trace)
        return trace

    # ------------------------------------------------------------------
    # record_step
    # ------------------------------------------------------------------

    def record_step(
        self,
        trace_id: str,
        step_id: str,
        skill_name: str,
        input_params: Any,
        output: Any,
        status: str,
        duration_ms: int,
        retry_count: int = 0,
        error: Optional[str] = None,
        tool_calls: Optional[List[ToolCallRecord]] = None,
    ) -> Optional[StepRecord]:
        """
        追加 StepRecord。
        大字段（input_params, output）超过阈值时自动外置引用。
        """
        trace = self._traces.get(trace_id)
        if not trace:
            logger.warning(f"[TraceCollector] trace {trace_id} not found, skipping step")
            return None

        input_ref = None
        output_ref = None
        threshold = self._config.large_field_threshold_bytes

        # 大字段外置引用
        serialized_input = self._safe_serialize(input_params)
        if len(serialized_input.encode("utf-8")) > threshold:
            input_ref = self._externalize(serialized_input)
            input_params = input_ref.summary  # 内联仅保留摘要

        serialized_output = self._safe_serialize(output)
        if len(serialized_output.encode("utf-8")) > threshold:
            output_ref = self._externalize(serialized_output)
            output = output_ref.summary

        step = StepRecord(
            step_id=step_id,
            trace_id=trace_id,
            skill_name=skill_name,
            input_params=input_params,
            input_params_ref=input_ref,
            output=output,
            output_ref=output_ref,
            status=status,
            duration_ms=duration_ms,
            retry_count=retry_count,
            error=error,
            tool_calls=tool_calls or [],
            timestamp=datetime.now(timezone.utc),
        )
        trace.steps.append(step)
        self._persist_step(step)
        return step

    # ------------------------------------------------------------------
    # record_artifact
    # ------------------------------------------------------------------

    def record_artifact(
        self,
        trace_id: str,
        step_id: str,
        artifact_type: str,
        path: str,
        content_hash: str,
        size_bytes: int,
        semantic_role: Optional[str] = None,
    ) -> Optional[ArtifactSnapshot]:
        """创建 ArtifactSnapshot，引用 ArtifactStore 中的实际内容。"""
        trace = self._traces.get(trace_id)
        if not trace:
            logger.warning(f"[TraceCollector] trace {trace_id} not found, skipping artifact")
            return None

        # 按 artifact_type 差异化阈值
        threshold = self._config.artifact_type_thresholds.get(
            artifact_type, self._config.artifact_size_threshold_bytes
        )

        snapshot = ArtifactSnapshot(
            artifact_id=str(uuid.uuid4()),
            trace_id=trace_id,
            step_id=step_id,
            artifact_type=artifact_type,
            semantic_role=semantic_role,
            path=path if size_bytes <= threshold else path,
            content_hash=content_hash,
            size_bytes=size_bytes,
            producer_step_id=step_id,
            timestamp=datetime.now(timezone.utc),
        )
        trace.artifacts.append(snapshot)
        self._persist_artifact(snapshot)
        return snapshot

    # ------------------------------------------------------------------
    # record_outcome
    # ------------------------------------------------------------------

    def record_outcome(
        self,
        trace_id: str,
        task_id: str,
        status: OutcomeStatus,
        failure_category: Optional[FailureCategory] = None,
        summary: str = "",
        decision_basis: str = "",
    ) -> Optional[OutcomeRecord]:
        """记录标准化任务结果，确保 trace_id 关联到对应 ExecutionTrace。"""
        trace = self._traces.get(trace_id)
        if not trace:
            logger.warning(f"[TraceCollector] trace {trace_id} not found, skipping outcome")
            return None

        outcome = OutcomeRecord(
            outcome_id=str(uuid.uuid4()),
            trace_id=trace_id,
            task_id=task_id,
            status=status,
            failure_category=failure_category,
            summary=summary,
            decision_basis=decision_basis,
            timestamp=datetime.now(timezone.utc),
        )
        trace.outcome = outcome
        self._persist_outcome(outcome)
        return outcome

    # ------------------------------------------------------------------
    # record_cost
    # ------------------------------------------------------------------

    def record_cost(
        self,
        trace_id: str,
        cost_telemetry: CostTelemetry,
    ) -> None:
        """记录成本遥测数据。"""
        trace = self._traces.get(trace_id)
        if not trace:
            logger.warning(f"[TraceCollector] trace {trace_id} not found, skipping cost")
            return
        trace.cost_telemetry = cost_telemetry
        self._persist_cost(trace_id, cost_telemetry)

    # ------------------------------------------------------------------
    # append_user_feedback
    # ------------------------------------------------------------------

    def append_user_feedback(
        self,
        trace_id: str,
        feedback: str,
    ) -> None:
        """追加用户反馈到 trace。"""
        trace = self._traces.get(trace_id)
        if not trace:
            logger.warning(f"[TraceCollector] trace {trace_id} not found, skipping feedback")
            return
        trace.user_feedback.append(feedback)
        self._try_db(lambda s: self._update_trace_field(
            s, trace_id, "user_feedback", json.dumps(trace.user_feedback)
        ))

    # ------------------------------------------------------------------
    # mark_trace_hole
    # ------------------------------------------------------------------

    def mark_trace_hole(
        self,
        trace_id: str,
        step_id: str,
        reason: str,
    ) -> None:
        """标记 trace 数据缺失，写入 trace_integrity_degraded 记录。"""
        trace = self._traces.get(trace_id)
        if not trace:
            return
        hole = TraceHole(step_id=step_id, reason=reason, timestamp=datetime.now(timezone.utc))
        trace.trace_holes.append(hole)
        self._try_db(lambda s: self._update_trace_field(
            s, trace_id, "trace_holes",
            json.dumps([{"step_id": h.step_id, "reason": h.reason, "timestamp": h.timestamp.isoformat()} for h in trace.trace_holes])
        ))

    # ------------------------------------------------------------------
    # finalize_trace — 任务结束时调用
    # ------------------------------------------------------------------

    def finalize_trace(self, trace_id: str) -> Optional[ExecutionTrace]:
        """任务结束时调用，标记 end_time，如有 trace_hole 写入降级记录。"""
        trace = self._traces.get(trace_id)
        if not trace:
            return None
        trace.end_time = datetime.now(timezone.utc)
        if trace.trace_holes:
            # 写入 trace_integrity_degraded 事件
            if self._step_trace_store:
                try:
                    self._step_trace_store.record_event(
                        session_id=trace.session_id,
                        event_type="trace_integrity_degraded",
                        task_id=trace.task_id,
                        payload={
                            "trace_id": trace_id,
                            "holes": [{"step_id": h.step_id, "reason": h.reason} for h in trace.trace_holes],
                        },
                    )
                except Exception:
                    pass
        self._try_db(lambda s: self._update_trace_field(s, trace_id, "end_time", trace.end_time))
        return trace

    def get_trace(self, trace_id: str) -> Optional[ExecutionTrace]:
        """获取内存中的 trace。"""
        return self._traces.get(trace_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _safe_serialize(self, value: Any) -> str:
        """安全序列化任意值为字符串。"""
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, default=str, ensure_ascii=False)
        except Exception:
            return str(value)

    def _externalize(self, content: str) -> ContentRef:
        """将大字段外置，返回引用。"""
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        path = f"/refs/{content_hash[:16]}.json"
        summary = content[:200] + "..." if len(content) > 200 else content
        return ContentRef(content_hash=content_hash, path=path, summary=summary)

    def _try_db(self, fn) -> None:
        """尝试数据库操作，失败不阻塞。"""
        try:
            with Session(self._engine) as session:
                fn(session)
                session.commit()
        except Exception as exc:
            logger.warning(f"[TraceCollector] DB write failed: {exc}")

    def _update_trace_field(self, session: Session, trace_id: str, field: str, value: Any) -> None:
        """更新 trace 表的单个字段。"""
        db_trace = session.get(ExecutionTraceDB, trace_id)
        if db_trace:
            setattr(db_trace, field, value)
            session.add(db_trace)

    def _persist_trace(self, trace: ExecutionTrace) -> None:
        """持久化 ExecutionTrace 到数据库。"""
        def _write(session: Session):
            db_obj = ExecutionTraceDB(
                trace_id=trace.trace_id,
                task_id=trace.task_id,
                session_id=trace.session_id,
                goal=trace.goal,
                task_type=trace.task_type,
                start_time=trace.start_time,
            )
            session.add(db_obj)
        self._try_db(_write)

    def _persist_step(self, step: StepRecord) -> None:
        """持久化 StepRecord 到数据库。"""
        def _write(session: Session):
            tool_calls_json = json.dumps(
                [{"tool_name": tc.tool_name, "arguments": tc.arguments, "result": tc.result, "latency_ms": tc.latency_ms} for tc in step.tool_calls],
                default=str, ensure_ascii=False,
            ) if step.tool_calls else None
            db_obj = StepRecordDB(
                step_id=step.step_id,
                trace_id=step.trace_id,
                skill_name=step.skill_name,
                input_summary=str(step.input_params)[:500] if step.input_params else "",
                input_ref_hash=step.input_params_ref.content_hash if step.input_params_ref else None,
                input_ref_path=step.input_params_ref.path if step.input_params_ref else None,
                output_summary=str(step.output)[:500] if step.output else "",
                output_ref_hash=step.output_ref.content_hash if step.output_ref else None,
                output_ref_path=step.output_ref.path if step.output_ref else None,
                status=step.status,
                duration_ms=step.duration_ms,
                retry_count=step.retry_count,
                error=step.error,
                tool_calls=tool_calls_json,
                timestamp=step.timestamp,
            )
            session.add(db_obj)
        self._try_db(_write)

    def _persist_artifact(self, snapshot: ArtifactSnapshot) -> None:
        """持久化 ArtifactSnapshot 到数据库。"""
        def _write(session: Session):
            db_obj = ArtifactSnapshotDB(
                artifact_id=snapshot.artifact_id,
                trace_id=snapshot.trace_id,
                step_id=snapshot.step_id,
                artifact_type=snapshot.artifact_type,
                semantic_role=snapshot.semantic_role,
                path=snapshot.path,
                content_hash=snapshot.content_hash,
                size_bytes=snapshot.size_bytes,
                producer_step_id=snapshot.producer_step_id,
                timestamp=snapshot.timestamp,
            )
            session.add(db_obj)
        self._try_db(_write)

    def _persist_outcome(self, outcome: OutcomeRecord) -> None:
        """持久化 OutcomeRecord 到数据库。"""
        def _write(session: Session):
            db_obj = OutcomeRecordDB(
                outcome_id=outcome.outcome_id,
                trace_id=outcome.trace_id,
                task_id=outcome.task_id,
                status=outcome.status.value,
                failure_category=outcome.failure_category.value if outcome.failure_category else None,
                summary=outcome.summary,
                decision_basis=outcome.decision_basis,
                timestamp=outcome.timestamp,
            )
            session.add(db_obj)
        self._try_db(_write)

    def _persist_cost(self, trace_id: str, cost: CostTelemetry) -> None:
        """持久化 CostTelemetry 到数据库。"""
        def _write(session: Session):
            db_obj = CostTelemetryDB(
                trace_id=trace_id,
                total_tokens=cost.total_tokens,
                prompt_tokens=cost.prompt_tokens,
                completion_tokens=cost.completion_tokens,
                total_time_ms=cost.total_time_ms,
                total_steps=cost.total_steps,
                retry_count=cost.retry_count,
                side_effect_intensity=json.dumps({k.value: v for k, v in cost.side_effect_intensity.items()}),
                model_name=cost.model_name,
                step_cost_breakdown=json.dumps(
                    [{"step_id": e.step_id, "tokens": e.tokens, "prompt_tokens": e.prompt_tokens,
                      "completion_tokens": e.completion_tokens, "duration_ms": e.duration_ms, "model_name": e.model_name}
                     for e in cost.step_cost_breakdown]
                ),
            )
            session.add(db_obj)
        self._try_db(_write)
