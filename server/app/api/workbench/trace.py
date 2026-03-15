"""
Trace Viewer API — readable execution trace interface.

Endpoints:
  GET /api/trace/{session_id}
  GET /api/trace/{session_id}/replay?event_index={n}
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trace", tags=["trace"])


def _get_trace_store():
    from app.avatar.runtime.graph.storage.step_trace_store import StepTraceStore
    return StepTraceStore()


def _build_derived_state_from_steps(
    step_traces: List[Dict[str, Any]],
    session_events: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Build derived state directly from step_traces + session_events.
    This is more reliable than reconstructing from event_traces.
    """
    steps: Dict[str, Dict[str, Any]] = {}
    artifacts: Dict[str, Dict[str, Any]] = {}
    repair_count = 0
    final_verdict: Optional[str] = None

    for s in step_traces:
        step_id = s.get("step_id", "")
        steps[step_id] = {
            "status": s.get("status", "unknown"),
            "skill": s.get("step_type") or "",
            "artifacts": s.get("artifact_ids") or [],
            "execution_time_s": s.get("execution_time_s"),
            "retry_count": s.get("retry_count", 0),
            "error_message": s.get("error_message"),
        }
        for art_id in (s.get("artifact_ids") or []):
            artifacts[art_id] = {"type": "file", "producer_step": step_id}

    for e in session_events:
        etype = e.get("event_type", "")
        payload = e.get("payload") or {}
        if etype == "repair_triggered":
            repair_count += 1
        elif etype in ("session_completed", "task_terminal"):
            final_verdict = payload.get("terminal_state") or payload.get("verdict") or payload.get("result_status")
        elif etype == "verification_result":
            verdict = payload.get("verdict") or payload.get("status")
            if verdict in ("PASS", "passed"):
                final_verdict = final_verdict or "PASS"

    return {
        "steps": steps,
        "artifacts": artifacts,
        "repair_count": repair_count,
        "final_verdict": final_verdict,
    }


@router.get("/{session_id}")
async def get_trace(session_id: str) -> Dict[str, Any]:
    """
    Return all trace data for a session:
    - session_events: session-level events (session_traces table)
    - step_traces: per-step execution records (step_traces table)
    - event_traces: fine-grained events (event_traces table)
    - derived_state: reconstructed summary
    """
    try:
        store = _get_trace_store()
        session_events = store.get_session_events(session_id=session_id)
        step_traces = store.get_step_traces(session_id=session_id)
        event_traces = store.get_event_traces(session_id=session_id)
        derived_state = _build_derived_state_from_steps(step_traces, session_events)
        # Merge all events for the timeline view (session + fine-grained)
        all_events = sorted(
            session_events + event_traces,
            key=lambda e: e.get("created_at") or "",
        )
        return {
            "session_id": session_id,
            "events": all_events,
            "step_traces": step_traces,
            "derived_state": derived_state,
        }
    except Exception as e:
        logger.error(f"[TraceViewer] get_trace failed for {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}/replay")
async def replay_trace(
    session_id: str,
    event_index: int = Query(default=0, ge=0, description="Number of events to replay up to"),
) -> Dict[str, Any]:
    """
    Return reconstructed state after the first N session events (step-by-step replay).
    """
    try:
        store = _get_trace_store()
        session_events = store.get_session_events(session_id=session_id)
        step_traces = store.get_step_traces(session_id=session_id)
        events_slice = session_events[:event_index]
        # For replay, only include steps that started before the slice cutoff
        cutoff = events_slice[-1]["created_at"] if events_slice else ""
        steps_slice = [s for s in step_traces if (s.get("created_at") or "") <= cutoff] if cutoff else []
        derived_state = _build_derived_state_from_steps(steps_slice, events_slice)
        return {
            "session_id": session_id,
            "event_index": event_index,
            "total_events": len(session_events),
            "replayed_events": events_slice,
            "derived_state": derived_state,
        }
    except Exception as e:
        logger.error(f"[TraceViewer] replay_trace failed for {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
