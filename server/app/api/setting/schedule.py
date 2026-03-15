# app/api/schedule.py
from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional, Dict, Any
from sqlmodel import Session, select
from pydantic import BaseModel
from datetime import datetime, timedelta

from app.db.database import engine
from app.db.task.schedule import Schedule
from app.db.task.task import Task, Run
from app.services.scheduler_service import scheduler_service

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/schedules", tags=["schedules"])

class CreateScheduleRequest(BaseModel):
    name: str
    cron: str
    task_goal: str

class UpdateDependenciesRequest(BaseModel):
    depends_on: List[str]

@router.get("/stats")
async def get_schedule_stats() -> Dict[str, Any]:
    """获取定时任务统计数据（只统计 scheduled task 触发的 Run）"""
    with Session(engine) as session:
        # 1. 基础统计
        total_schedules = session.exec(select(Schedule)).all()
        active_count = len([s for s in total_schedules if s.is_active])

        # 2. 只统计 task_mode="scheduled" 的 Task 下的 Run（最近7天）
        seven_days_ago = datetime.utcnow() - timedelta(days=7)

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

        # 3. 每日趋势（最近7天）
        trend = []
        for i in range(7):
            day = datetime.utcnow() - timedelta(days=6 - i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)

            day_runs = [r for r in runs if day_start <= r.created_at.replace(tzinfo=None) < day_end]
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
    intent = {
        "goal": req.task_goal, 
        "intent_type": "unknown", 
        "domain": "other",
        "params": {},
        "metadata": {"source": "api"}
    }
    try:
        s = scheduler_service.create_schedule(req.name, req.cron, intent)
        return s
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.patch("/{schedule_id}/dependencies")
async def update_dependencies(schedule_id: str, req: UpdateDependenciesRequest):
    """更新任务依赖关系"""
    with Session(engine) as session:
        s = session.get(Schedule, schedule_id)
        if not s:
            raise HTTPException(status_code=404, detail="Schedule not found")
        
        # 验证依赖任务是否存在
        for dep_id in req.depends_on:
            dep = session.get(Schedule, dep_id)
            if not dep:
                raise HTTPException(status_code=400, detail=f"Dependency {dep_id} not found")
            # 防止循环依赖（简单检查）
            if dep_id == schedule_id:
                raise HTTPException(status_code=400, detail="Cannot depend on itself")
        
        s.depends_on = req.depends_on if req.depends_on else None
        session.add(s)
        session.commit()
        session.refresh(s)
        
        # 推送更新事件
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
        
        # 更新 APScheduler
        try:
            if is_active:
                # 恢复：重新添加任务
                scheduler_service._add_job_to_scheduler(s)
            else:
                # 暂停：移除任务
                scheduler_service.scheduler.remove_job(schedule_id)
        except Exception as e:
            logger.warning(f"Failed to update scheduler: {e}")
        
        # 推送事件
        scheduler_service._emit_schedule_event('updated', s)
        
        return s

@router.put("/{schedule_id}")
async def update_schedule(schedule_id: str, req: CreateScheduleRequest):
    """更新定时任务（仅时间和频率）"""
    with Session(engine) as session:
        s = session.get(Schedule, schedule_id)
        if not s:
            raise HTTPException(status_code=404, detail="Schedule not found")
        
        # 更新字段
        s.name = req.name
        s.cron_expression = req.cron
        s.intent_spec = {
            **s.intent_spec,
            "goal": req.task_goal
        }
        
        session.add(s)
        session.commit()
        session.refresh(s)
        
        # 重新添加到 APScheduler
        try:
            scheduler_service.scheduler.remove_job(schedule_id)
        except Exception:
            pass
        scheduler_service._add_job_to_scheduler(s)
        
        # 推送更新事件
        scheduler_service._emit_schedule_event('updated', s)
        
        return s

@router.post("/{schedule_id}/run")
async def run_schedule_once(schedule_id: str):
    """立即执行一次定时任务（不影响原定时计划）"""
    with Session(engine) as session:
        s = session.get(Schedule, schedule_id)
        if not s:
            raise HTTPException(status_code=404, detail="Schedule not found")
        
        # 立即执行一次
        try:
            scheduler_service.execute_wrapper(s.id, s.intent_spec)
            return {"success": True, "message": "任务已提交执行"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"执行失败: {str(e)}")

@router.delete("/{schedule_id}")
async def delete_schedule(schedule_id: str):
    """Delete a schedule."""
    with Session(engine) as session:
        s = session.get(Schedule, schedule_id)
        if not s:
            raise HTTPException(status_code=404, detail="Schedule not found")
        
        session.delete(s)
        session.commit()
        
        # Also remove from APScheduler
        try:
            scheduler_service.scheduler.remove_job(schedule_id)
        except Exception:
            pass # Job might not verify exists
        
        # 推送删除事件
        scheduler_service._emit_schedule_event('deleted', s)
            
        return {"success": True, "id": schedule_id}

