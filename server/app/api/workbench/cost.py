# app/api/cost.py
"""
Cost & Budget Dashboard API

GET /cost/summary              — 全局汇总（总 token、总成本、session 数）
GET /cost/sessions             — 按 session 列出成本，支持排序和分页
GET /cost/sessions/{id}        — 单个 session 的 planner invocation 明细
GET /cost/trend?days=7         — 按天聚合的成本趋势（用于折线图）
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Query
from sqlmodel import Session, select, func

from app.db.database import engine
from app.db.system import ExecutionSession, PlannerInvocation

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cost", tags=["cost"])


@router.get("/summary")
async def get_cost_summary():
    """全局成本汇总。"""
    with Session(engine) as db:
        row = db.exec(
            select(
                func.count(ExecutionSession.id).label("total_sessions"),
                func.sum(ExecutionSession.planner_tokens).label("total_tokens"),
                func.sum(ExecutionSession.planner_cost_usd).label("total_cost_usd"),
                func.sum(ExecutionSession.planner_invocations).label("total_invocations"),
            )
        ).one()

    return {
        "total_sessions": row[0] or 0,
        "total_tokens": row[1] or 0,
        "total_cost_usd": round(row[2] or 0.0, 6),
        "total_invocations": row[3] or 0,
    }


@router.get("/sessions")
async def list_session_costs(
    limit: int = Query(50, ge=1, le=200),
    sort_by: str = Query("cost", pattern="^(cost|tokens|created_at)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
):
    """按 session 列出成本，支持按 cost/tokens/created_at 排序。"""
    with Session(engine) as db:
        stmt = select(ExecutionSession).where(
            ExecutionSession.planner_tokens > 0
        )
        col_map = {
            "cost": ExecutionSession.planner_cost_usd,
            "tokens": ExecutionSession.planner_tokens,
            "created_at": ExecutionSession.created_at,
        }
        col = col_map[sort_by]
        stmt = stmt.order_by(col.desc() if order == "desc" else col.asc()).limit(limit)
        sessions = db.exec(stmt).all()

    return [
        {
            "id": s.id,
            "goal": s.goal,
            "status": s.status,
            "result_status": s.result_status,
            "planner_tokens": s.planner_tokens,
            "planner_cost_usd": round(s.planner_cost_usd, 6),
            "planner_invocations": s.planner_invocations,
            "total_nodes": s.total_nodes,
            "completed_nodes": s.completed_nodes,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "completed_at": s.completed_at.isoformat() if s.completed_at else None,
        }
        for s in sessions
    ]


@router.get("/sessions/{session_id}")
async def get_session_cost_detail(session_id: str):
    """单个 session 的 planner invocation 明细列表。"""
    from fastapi import HTTPException

    with Session(engine) as db:
        session_obj = db.get(ExecutionSession, session_id)
        if not session_obj:
            raise HTTPException(status_code=404, detail="Session not found")

        invocations = db.exec(
            select(PlannerInvocation)
            .where(PlannerInvocation.session_id == session_id)
            .order_by(PlannerInvocation.invocation_index)
        ).all()

    return {
        "session_id": session_id,
        "goal": session_obj.goal,
        "total_tokens": session_obj.planner_tokens,
        "total_cost_usd": round(session_obj.planner_cost_usd, 6),
        "total_invocations": session_obj.planner_invocations,
        "invocations": [
            {
                "index": inv.invocation_index,
                "tokens_used": inv.tokens_used,
                "cost_usd": round(inv.cost_usd, 6),
                "latency_ms": inv.latency_ms,
                "input_summary": inv.input_summary,
                "output_summary": inv.output_summary,
                "timestamp": inv.timestamp.isoformat() if inv.timestamp else None,
            }
            for inv in invocations
        ],
    }


@router.get("/trend")
async def get_cost_trend(
    days: int = Query(7, ge=1, le=90),
):
    """
    按天聚合成本趋势，返回最近 N 天的每日 token/cost 数据。
    用于前端折线图。
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    with Session(engine) as db:
        sessions = db.exec(
            select(ExecutionSession)
            .where(ExecutionSession.created_at >= since)
            .where(ExecutionSession.planner_tokens > 0)
            .order_by(ExecutionSession.created_at)
        ).all()

    # 按日期聚合
    daily: dict = {}
    for s in sessions:
        if s.created_at is None:
            continue
        day = s.created_at.strftime("%Y-%m-%d")
        if day not in daily:
            daily[day] = {"date": day, "tokens": 0, "cost_usd": 0.0, "sessions": 0}
        daily[day]["tokens"] += s.planner_tokens
        daily[day]["cost_usd"] += s.planner_cost_usd
        daily[day]["sessions"] += 1

    # 补全缺失的日期（值为 0）
    result = []
    for i in range(days):
        day = (datetime.now(timezone.utc) - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        entry = daily.get(day, {"date": day, "tokens": 0, "cost_usd": 0.0, "sessions": 0})
        entry["cost_usd"] = round(entry["cost_usd"], 6)
        result.append(entry)

    return {"days": days, "trend": result}


# ---------------------------------------------------------------------------
# P2: BudgetAccount endpoints
# ---------------------------------------------------------------------------

@router.get("/session/{session_id}/budget")
async def get_session_budget_cost(session_id: str):
    """
    返回 BudgetAccount 统计的 session 成本（区分 declared_estimate 和 measured_runtime_cost）。
    """
    from app.avatar.runtime.policy.budget_account import BudgetAccount
    # BudgetAccount 是内存实例，此处返回 DB 中的 cost_records 聚合
    from sqlmodel import select, func
    from app.db.cost_record import CostRecordDB

    with Session(engine) as db:
        rows = db.exec(
            select(CostRecordDB).where(CostRecordDB.session_id == session_id)
        ).all()

    total_llm = sum(r.llm_cost for r in rows)
    total_skill = sum(r.skill_cost for r in rows)
    total_tokens = sum(r.token_count for r in rows)
    declared = sum(r.declared_estimate for r in rows)
    measured = sum(r.measured_runtime_cost for r in rows)

    return {
        "session_id": session_id,
        "total_cost": round(total_llm + total_skill, 6),
        "llm_cost": round(total_llm, 6),
        "skill_cost": round(total_skill, 6),
        "token_count": total_tokens,
        "declared_estimate": round(declared, 6),
        "measured_runtime_cost": round(measured, 6),
        "record_count": len(rows),
    }


@router.get("/task/{task_id}/budget")
async def get_task_budget_cost(task_id: str):
    """
    返回 BudgetAccount 统计的 task 成本（区分 declared_estimate 和 measured_runtime_cost）。
    """
    from app.db.cost_record import CostRecordDB

    with Session(engine) as db:
        rows = db.exec(
            select(CostRecordDB).where(CostRecordDB.task_id == task_id)
        ).all()

    total_llm = sum(r.llm_cost for r in rows)
    total_skill = sum(r.skill_cost for r in rows)
    total_tokens = sum(r.token_count for r in rows)
    declared = sum(r.declared_estimate for r in rows)
    measured = sum(r.measured_runtime_cost for r in rows)

    return {
        "task_id": task_id,
        "total_cost": round(total_llm + total_skill, 6),
        "llm_cost": round(total_llm, 6),
        "skill_cost": round(total_skill, 6),
        "token_count": total_tokens,
        "declared_estimate": round(declared, 6),
        "measured_runtime_cost": round(measured, 6),
        "record_count": len(rows),
    }


@router.get("/summary/budget")
async def get_budget_summary(
    session_id: Optional[str] = Query(default=None),
    time_range_start: Optional[str] = Query(default=None, description="ISO 8601 datetime"),
    time_range_end: Optional[str] = Query(default=None, description="ISO 8601 datetime"),
):
    """
    汇总成本，支持按 session_id 和时间范围过滤。
    明确区分 declared_estimate 和 measured_runtime_cost。
    """
    from app.db.cost_record import CostRecordDB
    from sqlmodel import select

    with Session(engine) as db:
        stmt = select(CostRecordDB)
        if session_id:
            stmt = stmt.where(CostRecordDB.session_id == session_id)
        if time_range_start:
            try:
                ts = datetime.fromisoformat(time_range_start)
                stmt = stmt.where(CostRecordDB.created_at >= ts)
            except ValueError:
                pass
        if time_range_end:
            try:
                te = datetime.fromisoformat(time_range_end)
                stmt = stmt.where(CostRecordDB.created_at <= te)
            except ValueError:
                pass
        rows = db.exec(stmt).all()

    total_llm = sum(r.llm_cost for r in rows)
    total_skill = sum(r.skill_cost for r in rows)
    total_tokens = sum(r.token_count for r in rows)
    declared = sum(r.declared_estimate for r in rows)
    measured = sum(r.measured_runtime_cost for r in rows)

    return {
        "filters": {
            "session_id": session_id,
            "time_range_start": time_range_start,
            "time_range_end": time_range_end,
        },
        "total_cost": round(total_llm + total_skill, 6),
        "llm_cost": round(total_llm, 6),
        "skill_cost": round(total_skill, 6),
        "token_count": total_tokens,
        "declared_estimate": round(declared, 6),
        "measured_runtime_cost": round(measured, 6),
        "record_count": len(rows),
    }
