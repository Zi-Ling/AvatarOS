# app/api/schedule.py
from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional, Dict, Any
from sqlmodel import Session, select
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone

from app.db.database import engine
from app.db.task.schedule import Schedule
from app.db.task.task import Task, Run
from app.services.scheduler_service import scheduler_service, _validate_cron

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/schedules", tags=["schedules"])


class CreateScheduleRequest(BaseModel):
    name: str
    cron: str
    task_goal: str
    description: Optional[str] = None


class UpdateDependenciesRequest(BaseModel):
    depends_on: List[str]


# ── 循环依赖检测 ──

def _detect_cycle(schedule_id: str, depends_on: List[str], session) -> Optional[str]:
    """BFS 检测间接循环依赖。返回环路描述或 None。"""
    visited = set()
    queue = list(depends_on)
    while queue:
        dep_id = queue.pop(0)
        if dep_id == schedule_id:
            return f"Circular dependency detected: ... → {dep_id} → {schedule_id}"
        if dep_id in visited:
            continue
        visited.add(dep_id)
        dep = session.get(Schedule, dep_id)
        if dep and dep.depends_on:
            queue.extend(dep.depends_on)
    return None


@router.get("/stats")
async def get_schedule_stats() -> Dict[str, Any]:
    """获取定时任务统计数据（只统计 scheduled task 触发的 Run）"""
    with Session(engine) as session:
        total_schedules = session.exec(select(Schedule)).all()
        active_count = len([s for s in total_schedules if s.is_active])

        now = datetime.now(timezone.utc)
        seven_days_ago = now - timedelta(days=7)

        scheduled_tasks = session.exec(
            select(Task).where(Task.task_mode == "scheduled")
        ).all()
        scheduled_task_ids = {t.id for t in scheduled_tasks}

        runs = session.exec(
            select(Run).where(
                Run.created_at >= seven_days_ago,
                Run.task_id.in_(scheduled_task_ids),  # type: ignore[attr-defined]
            )
        ).all() if scheduled_task_ids else []

        total_runs = len(runs)
        success_runs = len([r for r in runs if r.status == "completed"])
        failed_runs = len([r for r in runs if r.status == "failed"])
        success_rate = (success_runs / total_runs * 100) if total_runs > 0 else 0

        # 每日趋势（最近7天）
        trend = []
        for i in range(7):
            day = now - timedelta(days=6 - i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)

            day_runs = [r for r in runs if day_start <= r.created_at.replace(tzinfo=timezone.utc) < day_end]
            trend.append({
                "date": day.strftime("%m-%d"),
                "success": len([r for r in day_runs if r.status == "completed"]),
                "failed": len([r for r in day_runs if r.status == "failed"]),
                "total": len(day_runs),
            })

        return {
            "total_schedules": len(total_schedules),
            "active_schedules": active_count,
            "inactive_schedules": len(total_schedules) - active_count,
            "total_runs": total_runs,
            "success_runs": success_runs,
            "failed_runs": failed_runs,
            "success_rate": round(success_rate, 1),
            "trend": trend,
        }


@router.get("/")
async def list_schedules():
    """List all scheduled tasks."""
    with Session(engine) as session:
        schedules = session.exec(select(Schedule)).all()
        return schedules


@router.post("/")
async def create_schedule(req: CreateScheduleRequest):
    """Create a new schedule."""
    # Cron 表达式校验
    if not _validate_cron(req.cron):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid cron expression: '{req.cron}'. Expected 5-part format: minute hour day month day_of_week",
        )

    intent = {
        "goal": req.task_goal,
        "intent_type": "unknown",
        "domain": "other",
        "params": {},
        "metadata": {"source": "api"},
    }
    try:
        s = scheduler_service.create_schedule(req.name, req.cron, intent)
        # 回写 description
        if req.description:
            with Session(engine) as session:
                sched = session.get(Schedule, s.id)
                if sched:
                    sched.description = req.description
                    session.add(sched)
                    session.commit()
                    session.refresh(sched)
                    return sched
        return s
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{schedule_id}/dependencies")
async def update_dependencies(schedule_id: str, req: UpdateDependenciesRequest):
    """更新任务依赖关系（含完整循环依赖检测）"""
    with Session(engine) as session:
        s = session.get(Schedule, schedule_id)
        if not s:
            raise HTTPException(status_code=404, detail="Schedule not found")

        for dep_id in req.depends_on:
            dep = session.get(Schedule, dep_id)
            if not dep:
                raise HTTPException(status_code=400, detail=f"Dependency {dep_id} not found")
            if dep_id == schedule_id:
                raise HTTPException(status_code=400, detail="Cannot depend on itself")

        # 完整循环依赖检测（BFS）
        if req.depends_on:
            cycle = _detect_cycle(schedule_id, req.depends_on, session)
            if cycle:
                raise HTTPException(status_code=400, detail=cycle)

        s.depends_on = req.depends_on if req.depends_on else None
        session.add(s)
        session.commit()
        session.refresh(s)

        scheduler_service._emit_schedule_event('updated', s)
        return s


@router.patch("/{schedule_id}")
async def toggle_schedule(schedule_id: str, is_active: bool = Query(...)):
    """暂停或恢复定时任务"""
    with Session(engine) as session:
        s = session.get(Schedule, schedule_id)
        if not s:
            raise HTTPException(status_code=404, detail="Schedule not found")

        s.is_active = is_active
        session.add(s)
        session.commit()
        session.refresh(s)

        try:
            if is_active:
                scheduler_service._add_job_to_scheduler(s)
            else:
                scheduler_service.scheduler.remove_job(schedule_id)
        except Exception as e:
            logger.warning(f"Failed to update scheduler: {e}")

        scheduler_service._emit_schedule_event('updated', s)
        return s


@router.put("/{schedule_id}")
async def update_schedule(schedule_id: str, req: CreateScheduleRequest):
    """更新定时任务（名称、目标、时间、频率、描述）"""
    # Cron 表达式校验
    if not _validate_cron(req.cron):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid cron expression: '{req.cron}'. Expected 5-part format: minute hour day month day_of_week",
        )

    with Session(engine) as session:
        s = session.get(Schedule, schedule_id)
        if not s:
            raise HTTPException(status_code=404, detail="Schedule not found")

        s.name = req.name
        s.cron_expression = req.cron
        s.description = req.description
        s.intent_spec = {
            **s.intent_spec,
            "goal": req.task_goal,
        }
        s.updated_at = datetime.now(timezone.utc)

        session.add(s)
        session.commit()
        session.refresh(s)

        # 重新添加到 APScheduler
        try:
            scheduler_service.scheduler.remove_job(schedule_id)
        except Exception:
            pass
        scheduler_service._add_job_to_scheduler(s)

        scheduler_service._emit_schedule_event('updated', s)
        return s


@router.post("/{schedule_id}/run")
async def run_schedule_once(schedule_id: str):
    """立即执行一次定时任务（异步提交，不阻塞 API 请求）"""
    with Session(engine) as session:
        s = session.get(Schedule, schedule_id)
        if not s:
            raise HTTPException(status_code=404, detail="Schedule not found")

        # 异步提交到后台线程，不阻塞 HTTP 响应
        import asyncio
        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            None, scheduler_service.execute_wrapper, s.id, s.intent_spec
        )
        return {"success": True, "message": "任务已提交执行"}


@router.delete("/{schedule_id}")
async def delete_schedule(schedule_id: str):
    """Delete a schedule."""
    with Session(engine) as session:
        s = session.get(Schedule, schedule_id)
        if not s:
            raise HTTPException(status_code=404, detail="Schedule not found")

        session.delete(s)
        session.commit()

        try:
            scheduler_service.scheduler.remove_job(schedule_id)
        except Exception:
            pass

        scheduler_service._emit_schedule_event('deleted', s)
        return {"success": True, "id": schedule_id}
