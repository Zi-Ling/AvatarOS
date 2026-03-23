# app/api/history.py
"""
History API — 基于 ExecutionSession + StepTraceRecord

/history/sessions          列出最近执行会话
/history/sessions/{id}     会话详情（含结构化 step view model）
/history/sessions/{id}/events   细粒度 Event Trace 查询
/history/sessions/{id}/replay   Replay Engine（三种模式）
"""
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db.database import engine
from app.db.system import ExecutionSession
from app.avatar.runtime.graph.storage.step_trace_store import StepTraceRecord

router = APIRouter(prefix="/history", tags=["history"])


def _session_to_item(s: ExecutionSession) -> dict:
    return {
        "id": s.id,
        "goal": s.goal,
        "status": s.status,
        "result_status": s.result_status,
        "conversation_id": s.conversation_id,
        "workspace_path": s.workspace_path,
        "total_nodes": s.total_nodes,
        "completed_nodes": s.completed_nodes,
        "failed_nodes": s.failed_nodes,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "completed_at": s.completed_at.isoformat() if s.completed_at else None,
    }


def _step_to_view(r: StepTraceRecord) -> dict:
    artifact_ids = json.loads(r.artifact_ids_json) if r.artifact_ids_json else []
    duration_s = r.execution_time_s

    return {
        "id": r.id,
        "step_id": r.step_id,
        "step_type": r.step_type,
        "status": r.status,
        "summary": r.output_summary,
        "error_message": r.error_message,
        "artifact_ids": artifact_ids,
        "retry_count": r.retry_count,
        "timing": {
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "ended_at": r.ended_at.isoformat() if r.ended_at else None,
            "duration_s": duration_s,
        },
    }


@router.get("/sessions")
async def list_sessions(
    limit: int = Query(50, ge=1, le=200),
    conversation_id: Optional[str] = Query(None),
):
    """列出最近执行会话，可按 conversation_id（chat session）过滤"""
    with Session(engine) as db:
        stmt = select(ExecutionSession).order_by(ExecutionSession.created_at.desc()).limit(limit)
        if conversation_id:
            stmt = stmt.where(ExecutionSession.conversation_id == conversation_id)
        sessions = db.exec(stmt).all()
    return [_session_to_item(s) for s in sessions]


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """
    会话详情：ExecutionSession + 所有 StepTraceRecord。
    返回结构化 step view model，前端不做拼接。
    """
    with Session(engine) as db:
        session_obj = db.get(ExecutionSession, session_id)
        if not session_obj:
            raise HTTPException(status_code=404, detail="Session not found")

        steps = db.exec(
            select(StepTraceRecord)
            .where(StepTraceRecord.session_id == session_id)
            .order_by(StepTraceRecord.created_at)
        ).all()

    return {
        **_session_to_item(session_obj),
        "steps": [_step_to_view(s) for s in steps],
    }


@router.get("/sessions/{session_id}/artifacts")
async def list_session_artifacts(session_id: str):
    """
    列出某个 session 的所有 artifact，直接从 history 路径访问，无需跨 API 拼接。
    """
    from app.db.artifact_record import ArtifactRecord
    import json as _json

    with Session(engine) as db:
        session_obj = db.get(ExecutionSession, session_id)
        if not session_obj:
            raise HTTPException(status_code=404, detail="Session not found")
        records = db.exec(
            select(ArtifactRecord)
            .where(ArtifactRecord.session_id == session_id)
            .order_by(ArtifactRecord.created_at)
        ).all()

    def _to_dict(r: ArtifactRecord) -> dict:
        consumed = _json.loads(r.consumed_by_step_ids_json) if r.consumed_by_step_ids_json else []
        return {
            "artifact_id": r.artifact_id,
            "step_id": r.step_id,
            "filename": r.filename,
            "storage_uri": r.storage_uri,
            "size": r.size,
            "checksum": r.checksum,
            "mime_type": r.mime_type,
            "artifact_type": r.artifact_type,
            "consumed_by_step_ids": consumed,
            "created_at": r.created_at.isoformat(),
        }

    return {"session_id": session_id, "artifacts": [_to_dict(r) for r in records]}


@router.get("/sessions/{session_id}/timeline")
async def get_session_timeline(session_id: str):
    """
    轻量 GET 接口，直接返回 session 的三层事件时间线。
    不触发 replay 执行，只读 trace 数据。
    用于前端 Inspector 页面，无需 POST /replay。
    """
    from app.avatar.runtime.graph.storage.step_trace_store import get_step_trace_store
    from datetime import timezone

    with Session(engine) as db:
        session_obj = db.get(ExecutionSession, session_id)
        if not session_obj:
            raise HTTPException(status_code=404, detail="Session not found")

    store = get_step_trace_store()

    timeline = []

    # 层 1：Session 级事件
    try:
        for e in store.get_session_events(session_id):
            timeline.append({
                "layer": "session",
                "event_type": e["event_type"],
                "timestamp": e.get("created_at").isoformat() if e.get("created_at") else None,
                "payload": e.get("payload") or {},
            })
    except Exception:
        pass

    # 层 2：Step Trace
    try:
        for s in store.get_step_traces(session_id):
            base = {
                "layer": "step",
                "step_id": s["step_id"],
                "step_type": s.get("step_type"),
                "status": s["status"],
                "container_id": s.get("container_id"),
                "retry_count": s.get("retry_count", 0),
                "execution_time_s": s.get("execution_time_s"),
                "artifact_ids": s.get("artifact_ids") or [],
                "error_message": s.get("error_message"),
            }
            if s.get("started_at"):
                timeline.append({**base, "event_type": "step_started", "timestamp": s["started_at"].isoformat()})
            if s.get("ended_at"):
                timeline.append({**base, "event_type": f"step_{s['status']}", "timestamp": s["ended_at"].isoformat()})
    except Exception:
        pass

    # 层 3：细粒度 Event Trace
    try:
        for ev in store.get_event_traces(session_id):
            ts = ev.get("created_at")
            timeline.append({
                "layer": "event",
                "event_type": ev["event_type"],
                "timestamp": ts.isoformat() if ts else None,
                "step_id": ev.get("step_id"),
                "container_id": ev.get("container_id"),
                "artifact_id": ev.get("artifact_id"),
                "payload": ev.get("payload") or {},
            })
    except Exception:
        pass

    # 按时间排序（None 排最前）
    timeline.sort(key=lambda e: e["timestamp"] or "")

    summary = store.summarize_session(session_id)
    return {"session_id": session_id, "timeline": timeline, "summary": summary}


@router.get("/sessions/{session_id}/events")
async def get_session_events(
    session_id: str,
    step_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
):
    """
    细粒度 Event Trace 查询（第三层）。
    可按 step_id / event_type 过滤，用于 Inspector / 审计 / 问题定位。
    """
    from app.avatar.runtime.graph.storage.step_trace_store import get_step_trace_store
    with Session(engine) as db:
        session_obj = db.get(ExecutionSession, session_id)
        if not session_obj:
            raise HTTPException(status_code=404, detail="Session not found")

    store = get_step_trace_store()
    return store.get_event_traces(session_id, step_id=step_id, event_type=event_type)


# ---------------------------------------------------------------------------
# Replay API
# ---------------------------------------------------------------------------

class ReplayRequest(BaseModel):
    mode: str = "trace_only"   # trace_only | artifact_verification | deterministic_reexec
    reexec_config: Optional[dict] = None


def _replay_event_to_dict(e) -> dict:
    return {
        "event_type": e.event_type,
        "layer": e.layer,
        "timestamp": e.timestamp.isoformat() if e.timestamp else None,
        "session_id": e.session_id,
        "step_id": e.step_id,
        "container_id": e.container_id,
        "artifact_id": e.artifact_id,
        "payload": e.payload,
    }


def _artifact_verification_to_dict(r) -> dict:
    return {
        "artifact_id": r.artifact_id,
        "filename": r.filename,
        "storage_uri": r.storage_uri,
        "expected_checksum": r.expected_checksum,
        "actual_checksum": r.actual_checksum,
        "expected_size": r.expected_size,
        "actual_size": r.actual_size,
        "file_exists": r.file_exists,
        "checksum_match": r.checksum_match,
        "size_match": r.size_match,
        "passed": r.passed,
        "consumed_by_step_ids": r.consumed_by_step_ids,
    }


@router.post("/sessions/{session_id}/replay")
async def replay_session(session_id: str, body: ReplayRequest):
    """
    Replay Engine — 三种模式：

    - trace_only: 不执行，按 trace 还原完整事件时间线（UI Inspector / 审计）
    - artifact_verification: 校验 artifact checksum / 大小 / 文件存在性
    - deterministic_reexec: 在固定输入和 policy snapshot 下重新执行（需要完整 trace 数据）
    """
    from app.avatar.runtime.graph.storage.replay_engine import ReplayEngine, ReplayMode

    with Session(engine) as db:
        session_obj = db.get(ExecutionSession, session_id)
        if not session_obj:
            raise HTTPException(status_code=404, detail="Session not found")

    try:
        mode = ReplayMode(body.mode)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid replay mode '{body.mode}'. "
                   f"Valid: trace_only, artifact_verification, deterministic_reexec",
        )

    replay_engine = ReplayEngine()
    result = await replay_engine.replay(
        session_id=session_id,
        mode=mode,
        reexec_config=body.reexec_config,
    )

    response: dict = {
        "session_id": result.session_id,
        "mode": result.mode,
        "success": result.success,
        "error_message": result.error_message,
        "replayed_at": result.replayed_at.isoformat(),
    }

    if mode == ReplayMode.TRACE_ONLY:
        response["timeline"] = [_replay_event_to_dict(e) for e in result.timeline]
        response["session_summary"] = result.session_summary

    elif mode == ReplayMode.ARTIFACT_VERIFICATION:
        response["artifacts_total"] = result.artifacts_total
        response["artifacts_passed"] = result.artifacts_passed
        response["artifacts_failed"] = result.artifacts_failed
        response["artifact_results"] = [
            _artifact_verification_to_dict(r) for r in result.artifact_results
        ]

    elif mode == ReplayMode.DETERMINISTIC_REEXEC:
        response["reexec_session_id"] = result.reexec_session_id
        response["reexec_status"] = result.reexec_status

    return response
