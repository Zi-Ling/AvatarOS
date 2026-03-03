# app/api/history.py
from fastapi import APIRouter, Query, HTTPException
from typing import List, Optional
from sqlmodel import Session, select

from app.db.database import engine
from app.db.task.task import Task, Run, Step
from app.services.task_service import task_service

router = APIRouter(prefix="/history", tags=["history"])

@router.get("/tasks")
async def list_tasks(limit: int = Query(50, ge=1, le=100)):
    """Get recent tasks."""
    tasks = task_service.get_recent_tasks(limit)
    return tasks

@router.get("/tasks/{task_id}")
async def get_task_details(task_id: str):
    """Get full details of a task including runs and steps."""
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        # Trigger lazy loading or fetch manually
        # SQLModel relations should load automatically if accessed, but let's be explicit for API response
        # We want to return a nested structure: Task -> [Run -> [Step]]
        
        # Since SQLModel default response might not include relations by default depending on configuration,
        # let's construct a dict response
        
        res = task.model_dump()
        
        runs = session.exec(select(Run).where(Run.task_id == task.id).order_by(Run.created_at.desc())).all()
        res["runs"] = []
        
        for r in runs:
            r_dict = r.model_dump()
            steps = session.exec(select(Step).where(Step.run_id == r.id).order_by(Step.step_index)).all()
            r_dict["steps"] = [s.model_dump() for s in steps]
            res["runs"].append(r_dict)
            
        return res

