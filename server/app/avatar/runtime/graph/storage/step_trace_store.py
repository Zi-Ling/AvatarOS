# app/avatar/runtime/graph/storage/step_trace_store.py
# StepTraceStore - 执行证据链（append-only）
# SessionTraceRecord 使用 event_type + payload_json 统一结构，避免字段爆炸。
# 支持的 event_type：session_created/session_planned/session_running/
#   plan_generated/policy_decision/node_completed/node_failed/
#   session_completed/session_failed/session_cancelled/invalid_transition

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlmodel import Field, SQLModel, Session, select

logger = logging.getLogger(__name__)

_SUMMARY_MAX = 500


def _summarize(obj: Any, max_len: int = _SUMMARY_MAX) -> str:
    s = json.dumps(obj, default=str, ensure_ascii=False)
    return s if len(s) <= max_len else s[:max_len] + "..."


class SessionTraceRecord(SQLModel, table=True):
    __tablename__ = "session_traces"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    task_id: Optional[str] = Field(default=None)
    event_type: str = Field(index=True)
    payload_json: Optional[str] = Field(default=None)
    summary: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StepTraceRecord(SQLModel, table=True):
    __tablename__ = "step_traces"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    graph_id: Optional[str] = Field(default=None, index=True)
    step_id: str = Field(index=True)
    step_type: Optional[str] = Field(default=None)
    status: str
    started_at: Optional[datetime] = Field(default=None)
    ended_at: Optional[datetime] = Field(default=None)
    execution_time_s: Optional[float] = Field(default=None)
    retry_count: int = Field(default=0)
    error_code: Optional[str] = Field(default=None)
    error_message: Optional[str] = Field(default=None)
    container_id: Optional[str] = Field(default=None)
    sandbox_backend: Optional[str] = Field(default=None)
    workspace_path: Optional[str] = Field(default=None)
    stdout_ref: Optional[str] = Field(default=None)
    stderr_ref: Optional[str] = Field(default=None)
    artifact_ids_json: Optional[str] = Field(default=None)
    input_summary: Optional[str] = Field(default=None)
    output_summary: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StepTraceStore:

    def __init__(self, engine=None):
        if engine is None:
            from app.db.database import engine as default_engine
            engine = default_engine
        self._engine = engine
        logger.info("[StepTraceStore] Initialized")

    def record_session_event(
        self,
        session_id: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None,
    ) -> None:
        payload = payload or {}
        record = SessionTraceRecord(
            session_id=session_id,
            task_id=task_id,
            event_type=event_type,
            payload_json=json.dumps(payload, default=str, ensure_ascii=False),
            summary=_summarize(payload),
        )
        with Session(self._engine) as db:
            db.add(record)
            db.commit()
        logger.debug(f"[StepTraceStore] session_event session={session_id} type={event_type}")

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
        logger.debug(f"[StepTraceStore] step_trace session={session_id} step={step_id} status={status}")

    def get_session_events(self, session_id: str) -> List[Dict[str, Any]]:
        with Session(self._engine) as db:
            records = db.exec(
                select(SessionTraceRecord)
                .where(SessionTraceRecord.session_id == session_id)
                .order_by(SessionTraceRecord.created_at)
            ).all()
        result = []
        for r in records:
            d = r.model_dump()
            d["payload"] = json.loads(r.payload_json) if r.payload_json else {}
            result.append(d)
        return result

    def get_step_traces(self, session_id: str) -> List[Dict[str, Any]]:
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
        events = self.get_session_events(session_id)
        steps = self.get_step_traces(session_id)

        all_artifacts: List[str] = []
        failed_steps: List[str] = []
        containers: List[str] = []

        for s in steps:
            all_artifacts.extend(s.get("artifact_ids") or [])
            if s["status"] == "failed":
                failed_steps.append(s["step_id"])
            if s.get("container_id"):
                containers.append(s["container_id"])

        final_status = None
        for e in reversed(events):
            p = e.get("payload") or {}
            if p.get("result_status"):
                final_status = p["result_status"]
                break

        return {
            "session_id": session_id,
            "total_steps": len(steps),
            "failed_steps": failed_steps,
            "artifact_ids": list(set(all_artifacts)),
            "containers": list(set(containers)),
            "session_events": [e["event_type"] for e in events],
            "final_status": final_status,
        }

