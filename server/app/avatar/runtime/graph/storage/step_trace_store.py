# app/avatar/runtime/graph/storage/step_trace_store.py

"""
StepTraceStore — 执行证据链

append-only 的 step 级 trace 记录，独立于 StateStore 的 checkpoint 机制。

设计原则：
- append-only：只写不改历史，每个事件是一条独立记录
- 与 session / step / artifact / sandbox 四类对象绑定
- 不是结构化日志（那是 observability/logger.py 的职责）
- 是执行证据链：一个 session 结束后能完整回答"发生了什么"

当前阶段覆盖：
  A. session trace  — session 生命周期事件
  B. step trace     — 每个 step 的执行记录（含 sandbox + artifact 信息）

后续扩展：
  - artifact lineage（跨 step artifact 依赖图）
  - replay engine（基于 trace 重放）
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlmodel import Field, SQLModel, Session, select, create_engine

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# DB Models
# ──────────────────────────────────────────────

class SessionTraceRecord(SQLModel, table=True):
    """Session 生命周期事件（append-only）"""
    __tablename__ = "session_traces"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    task_id: Optional[str] = None
    event: str                          # created / planned / running / completed / failed
    final_status: Optional[str] = None  # 仅 completed/failed 时填写
    planner_summary: Optional[str] = None
    metadata_json: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StepTraceRecord(SQLModel, table=True):
    """Step 执行记录（append-only）"""
    __tablename__ = "step_traces"

    id: Optional[int] = Field(default=None, primary_key=True)

    # 归属
    session_id: str = Field(index=True)
    graph_id: Optional[str] = Field(default=None, index=True)
    step_id: str = Field(index=True)    # node.id
    step_type: Optional[str] = None     # capability_name

    # 执行结果
    status: str                         # success / failed / skipped
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    execution_time_s: Optional[float] = None
    retry_count: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    # Sandbox 信息
    container_id: Optional[str] = None
    sandbox_backend: Optional[str] = None  # kata / docker / process / local
    workspace_path: Optional[str] = None
    stdout_ref: Optional[str] = None    # logs/ 下的文件路径或摘要
    stderr_ref: Optional[str] = None

    # Artifact 信息（JSON 数组）
    artifact_ids_json: Optional[str] = None   # ["id1", "id2"]

    # 输入/输出摘要（不存全量，只存摘要）
    input_summary: Optional[str] = None
    output_summary: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)


# ──────────────────────────────────────────────
# Store
# ──────────────────────────────────────────────

class StepTraceStore:
    """
    写入和查询 step 级执行证据链。

    用法（在 NodeRunner 执行完后调用）：
        trace_store.record_step(
            session_id=...,
            graph_id=...,
            step_id=node.id,
            step_type=node.capability_name,
            status="success",
            started_at=start_time,
            ended_at=end_time,
            artifact_ids=["id1"],
            ...
        )
    """

    def __init__(self, engine=None):
        if engine is None:
            from app.db.database import engine as default_engine
            engine = default_engine

        self._engine = engine
        SQLModel.metadata.create_all(self._engine, tables=[
            SessionTraceRecord.__table__,
            StepTraceRecord.__table__,
        ])
        logger.info("[StepTraceStore] Initialized")

    # ------------------------------------------------------------------
    # Session trace
    # ------------------------------------------------------------------

    def record_session_event(
        self,
        session_id: str,
        event: str,
        task_id: Optional[str] = None,
        final_status: Optional[str] = None,
        planner_summary: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """记录 session 生命周期事件（append-only）"""
        record = SessionTraceRecord(
            session_id=session_id,
            task_id=task_id,
            event=event,
            final_status=final_status,
            planner_summary=planner_summary,
            metadata_json=json.dumps(metadata, default=str) if metadata else None,
        )
        with Session(self._engine) as session:
            session.add(record)
            session.commit()
        logger.debug(f"[StepTraceStore] session_event session={session_id} event={event}")

    # ------------------------------------------------------------------
    # Step trace
    # ------------------------------------------------------------------

    def record_step(
        self,
        session_id: str,
        step_id: str,
        status: str,
        graph_id: Optional[str] = None,
        step_type: Optional[str] = None,
        started_at: Optional[datetime] = None,
        ended_at: Optional[datetime] = None,
        execution_time_s: Optional[float] = None,
        retry_count: int = 0,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        container_id: Optional[str] = None,
        sandbox_backend: Optional[str] = None,
        workspace_path: Optional[str] = None,
        stdout_ref: Optional[str] = None,
        stderr_ref: Optional[str] = None,
        artifact_ids: Optional[List[str]] = None,
        input_summary: Optional[str] = None,
        output_summary: Optional[str] = None,
    ) -> None:
        """记录一条 step 执行 trace（append-only）"""
        record = StepTraceRecord(
            session_id=session_id,
            graph_id=graph_id,
            step_id=step_id,
            step_type=step_type,
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            execution_time_s=execution_time_s,
            retry_count=retry_count,
            error_code=error_code,
            error_message=error_message,
            container_id=container_id,
            sandbox_backend=sandbox_backend,
            workspace_path=workspace_path,
            stdout_ref=stdout_ref,
            stderr_ref=stderr_ref,
            artifact_ids_json=json.dumps(artifact_ids) if artifact_ids else None,
            input_summary=input_summary,
            output_summary=output_summary,
        )
        with Session(self._engine) as db:
            db.add(record)
            db.commit()
        logger.debug(
            f"[StepTraceStore] step_trace session={session_id} "
            f"step={step_id} status={status} artifacts={artifact_ids or []}"
        )

    # ------------------------------------------------------------------
    # 查询（供 inspector / replay 使用）
    # ------------------------------------------------------------------

    def get_session_events(self, session_id: str) -> List[Dict[str, Any]]:
        """获取 session 所有事件（按时间排序）"""
        with Session(self._engine) as db:
            records = db.exec(
                select(SessionTraceRecord)
                .where(SessionTraceRecord.session_id == session_id)
                .order_by(SessionTraceRecord.created_at)
            ).all()
        return [r.model_dump() for r in records]

    def get_step_traces(self, session_id: str) -> List[Dict[str, Any]]:
        """获取 session 所有 step trace（按时间排序）"""
        with Session(self._engine) as db:
            records = db.exec(
                select(StepTraceRecord)
                .where(StepTraceRecord.session_id == session_id)
                .order_by(StepTraceRecord.created_at)
            ).all()
        result = []
        for r in records:
            d = r.model_dump()
            d["artifact_ids"] = json.loads(r.artifact_ids_json) if r.artifact_ids_json else []
            result.append(d)
        return result

    def summarize_session(self, session_id: str) -> Dict[str, Any]:
        """
        回答"这个 session 发生了什么"：
          - 规划了什么
          - 跑了几个 step
          - 用了哪个 container
          - 写出了哪些文件
          - 哪一步失败
          - 是否有 artifact 产出
        """
        events = self.get_session_events(session_id)
        steps  = self.get_step_traces(session_id)

        all_artifacts: List[str] = []
        failed_steps:  List[str] = []
        containers:    List[str] = []

        for s in steps:
            all_artifacts.extend(s.get("artifact_ids") or [])
            if s["status"] == "failed":
                failed_steps.append(s["step_id"])
            if s.get("container_id"):
                containers.append(s["container_id"])

        return {
            "session_id":    session_id,
            "total_steps":   len(steps),
            "failed_steps":  failed_steps,
            "artifact_ids":  list(set(all_artifacts)),
            "containers":    list(set(containers)),
            "session_events": [e["event"] for e in events],
            "final_status":  next(
                (e["final_status"] for e in reversed(events) if e.get("final_status")),
                None
            ),
        }
