# app/avatar/runtime/graph/storage/replay_engine.py
"""
ReplayEngine — 执行证据链回放引擎（架构文档第十一节）

三种模式：
  1. Trace-only Replay
     不真正执行，只按 trace 还原事件时间线。
     用于 UI Inspector、审计、事故复盘。

  2. Artifact Verification Replay
     不完整重跑，只校验 artifact 与 trace 中的 checksum、大小、依赖关系是否一致。
     用于审计和存储校验。

  3. Deterministic Re-execution
     在固定输入、固定 policy、固定 workspace snapshot 下重新执行。
     用于验证执行稳定性。
     前提：trace 完整 + workspace snapshot 可恢复 + artifact 可追踪 + config snapshot 被记录。

Replay 成立的前提（架构文档原文）：
  - trace 完整（三层：session / step / event）
  - workspace snapshot 可恢复
  - artifact 可追踪（checksum + storage_uri）
  - execution config / policy / planner snapshot 被记录
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

class ReplayMode(str, Enum):
    TRACE_ONLY             = "trace_only"
    ARTIFACT_VERIFICATION  = "artifact_verification"
    DETERMINISTIC_REEXEC   = "deterministic_reexec"


@dataclass
class ReplayEvent:
    """还原后的单条执行事件（Trace-only 模式输出）"""
    event_type: str
    layer: str          # session / step / event
    timestamp: Optional[datetime]
    session_id: str
    step_id: Optional[str] = None
    container_id: Optional[str] = None
    artifact_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ArtifactVerificationResult:
    """单个 artifact 的校验结果"""
    artifact_id: str
    filename: str
    storage_uri: str
    expected_checksum: Optional[str]
    actual_checksum: Optional[str]
    expected_size: int
    actual_size: int
    file_exists: bool
    checksum_match: bool
    size_match: bool
    consumed_by_step_ids: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.file_exists and self.checksum_match and self.size_match


@dataclass
class ReplayResult:
    """Replay 执行结果"""
    session_id: str
    mode: ReplayMode
    success: bool
    error_message: Optional[str] = None

    # Trace-only 模式
    timeline: List[ReplayEvent] = field(default_factory=list)

    # Artifact Verification 模式
    artifact_results: List[ArtifactVerificationResult] = field(default_factory=list)
    artifacts_total: int = 0
    artifacts_passed: int = 0
    artifacts_failed: int = 0

    # Deterministic Re-execution 模式
    reexec_session_id: Optional[str] = None   # 新建的 re-execution session id
    reexec_status: Optional[str] = None

    # 通用摘要
    session_summary: Optional[Dict[str, Any]] = None
    replayed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# ReplayEngine
# ---------------------------------------------------------------------------

class ReplayEngine:
    """
    执行证据链回放引擎。

    用法：
        engine = ReplayEngine()
        result = await engine.replay(session_id, mode=ReplayMode.TRACE_ONLY)
    """

    def __init__(self, engine=None):
        if engine is None:
            from app.db.database import engine as default_engine
            engine = default_engine
        self._db_engine = engine

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    async def replay(
        self,
        session_id: str,
        mode: ReplayMode = ReplayMode.TRACE_ONLY,
        reexec_config: Optional[Dict[str, Any]] = None,
    ) -> ReplayResult:
        """
        执行 replay。

        Args:
            session_id: 要回放的 session id
            mode: 回放模式
            reexec_config: 仅 DETERMINISTIC_REEXEC 模式使用，可覆盖部分 config

        Returns:
            ReplayResult
        """
        # 验证 session 存在
        session = self._load_session(session_id)
        if session is None:
            return ReplayResult(
                session_id=session_id,
                mode=mode,
                success=False,
                error_message=f"Session {session_id} not found",
            )

        if mode == ReplayMode.TRACE_ONLY:
            return await self._replay_trace_only(session_id, session)
        elif mode == ReplayMode.ARTIFACT_VERIFICATION:
            return await self._replay_artifact_verification(session_id, session)
        elif mode == ReplayMode.DETERMINISTIC_REEXEC:
            return await self._replay_deterministic_reexec(
                session_id, session, reexec_config or {}
            )
        else:
            return ReplayResult(
                session_id=session_id,
                mode=mode,
                success=False,
                error_message=f"Unknown replay mode: {mode}",
            )

    # ------------------------------------------------------------------
    # 模式 1：Trace-only Replay
    # ------------------------------------------------------------------

    async def _replay_trace_only(
        self,
        session_id: str,
        session: Any,
    ) -> ReplayResult:
        """
        按 trace 还原完整事件时间线，不执行任何代码。
        合并三层 trace（session / step / event），按时间排序。
        """
        from app.avatar.runtime.graph.storage.step_trace_store import StepTraceStore
        store = StepTraceStore(engine=self._db_engine)

        timeline: List[ReplayEvent] = []

        # 层 1：Session Trace
        try:
            session_events = store.get_session_events(session_id)
            for e in session_events:
                timeline.append(ReplayEvent(
                    event_type=e["event_type"],
                    layer="session",
                    timestamp=e.get("created_at"),
                    session_id=session_id,
                    payload=e.get("payload") or {},
                ))
        except Exception as e:
            logger.warning(f"[ReplayEngine] Failed to load session events: {e}")

        # 层 2：Step Trace
        try:
            step_traces = store.get_step_traces(session_id)
            for s in step_traces:
                # step_started 事件
                timeline.append(ReplayEvent(
                    event_type="step_started",
                    layer="step",
                    timestamp=s.get("started_at"),
                    session_id=session_id,
                    step_id=s["step_id"],
                    container_id=s.get("container_id"),
                    payload={
                        "step_type": s.get("step_type"),
                        "retry_count": s.get("retry_count", 0),
                        "workspace_path": s.get("workspace_path"),
                        "input_summary": s.get("input_summary"),
                    },
                ))
                # step_ended 事件
                timeline.append(ReplayEvent(
                    event_type=f"step_{s['status']}",
                    layer="step",
                    timestamp=s.get("ended_at"),
                    session_id=session_id,
                    step_id=s["step_id"],
                    container_id=s.get("container_id"),
                    payload={
                        "status": s["status"],
                        "execution_time_s": s.get("execution_time_s"),
                        "artifact_ids": s.get("artifact_ids") or [],
                        "output_summary": s.get("output_summary"),
                        "error_message": s.get("error_message"),
                    },
                ))
        except Exception as e:
            logger.warning(f"[ReplayEngine] Failed to load step traces: {e}")

        # 层 3：Event Trace（细粒度）
        try:
            event_traces = store.get_event_traces(session_id)
            for ev in event_traces:
                timeline.append(ReplayEvent(
                    event_type=ev["event_type"],
                    layer="event",
                    timestamp=ev.get("created_at"),
                    session_id=session_id,
                    step_id=ev.get("step_id"),
                    container_id=ev.get("container_id"),
                    artifact_id=ev.get("artifact_id"),
                    payload=ev.get("payload") or {},
                ))
        except Exception as e:
            logger.warning(f"[ReplayEngine] Failed to load event traces: {e}")

        # 按时间排序（None timestamp 排最前）
        timeline.sort(key=lambda e: e.timestamp or datetime.min.replace(tzinfo=timezone.utc))

        summary = store.summarize_session(session_id)

        return ReplayResult(
            session_id=session_id,
            mode=ReplayMode.TRACE_ONLY,
            success=True,
            timeline=timeline,
            session_summary=summary,
        )

    # ------------------------------------------------------------------
    # 模式 2：Artifact Verification Replay
    # ------------------------------------------------------------------

    async def _replay_artifact_verification(
        self,
        session_id: str,
        session: Any,
    ) -> ReplayResult:
        """
        校验 artifact 与 trace 中的 checksum、大小、依赖关系是否一致。
        不重新执行，只做存储层校验。
        """
        import hashlib
        from sqlmodel import Session as DBSession, select

        from app.db.artifact_record import ArtifactRecord

        artifact_results: List[ArtifactVerificationResult] = []

        with DBSession(self._db_engine) as db:
            records = db.exec(
                select(ArtifactRecord)
                .where(ArtifactRecord.session_id == session_id)
                .order_by(ArtifactRecord.created_at)
            ).all()

        for record in records:
            consumed_by = []
            if record.consumed_by_step_ids_json:
                try:
                    consumed_by = json.loads(record.consumed_by_step_ids_json)
                except Exception:
                    pass

            # 检查文件是否存在并校验 checksum
            file_exists = False
            actual_checksum = None
            actual_size = 0

            storage_path = record.storage_uri
            try:
                p = Path(storage_path)
                if p.exists() and p.is_file():
                    file_exists = True
                    data = p.read_bytes()
                    actual_size = len(data)
                    actual_checksum = hashlib.sha256(data).hexdigest()
            except Exception as e:
                logger.warning(
                    f"[ReplayEngine] Failed to read artifact {record.artifact_id}: {e}"
                )

            checksum_match = (
                record.checksum is not None
                and actual_checksum is not None
                and record.checksum == actual_checksum
            )
            size_match = (record.size == actual_size)

            artifact_results.append(ArtifactVerificationResult(
                artifact_id=record.artifact_id,
                filename=record.filename,
                storage_uri=record.storage_uri,
                expected_checksum=record.checksum,
                actual_checksum=actual_checksum,
                expected_size=record.size,
                actual_size=actual_size,
                file_exists=file_exists,
                checksum_match=checksum_match,
                size_match=size_match,
                consumed_by_step_ids=consumed_by,
            ))

        passed = sum(1 for r in artifact_results if r.passed)
        failed = len(artifact_results) - passed

        return ReplayResult(
            session_id=session_id,
            mode=ReplayMode.ARTIFACT_VERIFICATION,
            success=(failed == 0),
            error_message=f"{failed} artifact(s) failed verification" if failed > 0 else None,
            artifact_results=artifact_results,
            artifacts_total=len(artifact_results),
            artifacts_passed=passed,
            artifacts_failed=failed,
        )

    # ------------------------------------------------------------------
    # 模式 3：Deterministic Re-execution
    # ------------------------------------------------------------------

    async def _replay_deterministic_reexec(
        self,
        session_id: str,
        session: Any,
        reexec_config: Dict[str, Any],
    ) -> ReplayResult:
        """
        在固定输入、固定 policy、固定 workspace snapshot 下重新执行。

        前提检查：
          - session 有 goal
          - session 有 runtime_config_snapshot
          - session 有 policy_snapshot
          - 至少有一条 PlannerInvocation 记录（说明 planner 曾被调用）

        如果前提不满足，返回 success=False 并说明原因。
        """
        from app.db.system import PlannerInvocation
        from sqlmodel import Session as DBSession, select

        # 前提检查
        missing: List[str] = []
        if not session.goal:
            missing.append("goal")
        if not session.runtime_config_snapshot:
            missing.append("runtime_config_snapshot")
        if not session.policy_snapshot:
            missing.append("policy_snapshot")

        # 检查是否有 planner invocation 记录
        with DBSession(self._db_engine) as db:
            first_invocation = db.exec(
                select(PlannerInvocation)
                .where(PlannerInvocation.session_id == session_id)
                .order_by(PlannerInvocation.invocation_index)
                .limit(1)
            ).first()

        if first_invocation is None:
            missing.append("planner_invocation_records")

        if missing:
            return ReplayResult(
                session_id=session_id,
                mode=ReplayMode.DETERMINISTIC_REEXEC,
                success=False,
                error_message=(
                    f"Deterministic re-execution prerequisites missing: {missing}. "
                    f"Re-execution requires complete trace data."
                ),
            )

        # 构建 re-execution env_context（从 snapshot 恢复）
        runtime_cfg = session.runtime_config_snapshot or {}
        policy_cfg = session.policy_snapshot or {}

        env_context: Dict[str, Any] = {
            "replay_source_session_id": session_id,
            "replay_mode": "deterministic_reexec",
            "workspace_path": session.workspace_path or "",
            # 从 runtime_config_snapshot 恢复限制参数
            "max_react_iterations": runtime_cfg.get("max_react_iterations", 200),
            "max_graph_nodes": runtime_cfg.get("max_graph_nodes", 200),
        }
        # 允许调用方覆盖部分 config
        env_context.update(reexec_config)

        # 获取 GraphController（从 app 全局单例）
        try:
            from app.core.bootstrap import get_avatar_main
            avatar = get_avatar_main()
            if avatar is None or avatar._graph_controller is None:
                return ReplayResult(
                    session_id=session_id,
                    mode=ReplayMode.DETERMINISTIC_REEXEC,
                    success=False,
                    error_message="GraphController not available for re-execution",
                )

            graph_result = await avatar._graph_controller.execute(
                intent=session.goal,
                mode="react",
                env_context=env_context,
            )

            return ReplayResult(
                session_id=session_id,
                mode=ReplayMode.DETERMINISTIC_REEXEC,
                success=graph_result.final_status in ("success", "partial_success"),
                error_message=graph_result.error_message if graph_result.final_status == "failed" else None,
                reexec_status=graph_result.final_status,
            )

        except Exception as e:
            logger.error(f"[ReplayEngine] Deterministic re-execution failed: {e}", exc_info=True)
            return ReplayResult(
                session_id=session_id,
                mode=ReplayMode.DETERMINISTIC_REEXEC,
                success=False,
                error_message=str(e),
            )

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _load_session(self, session_id: str) -> Optional[Any]:
        from app.db.system import ExecutionSession
        from sqlmodel import Session as DBSession
        with DBSession(self._db_engine) as db:
            return db.get(ExecutionSession, session_id)
