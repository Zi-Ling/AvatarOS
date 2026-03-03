# app/api/task/task.py
"""
任务管理接口
"""
from fastapi import APIRouter, HTTPException, Depends

from app.api.task.models import TaskResponse
from app.avatar.runtime.main import AvatarMain
from app.core.dependencies import get_avatar_runtime


router = APIRouter()


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    runtime: AvatarMain = Depends(get_avatar_runtime),
):
    """
    获取任务详情
    """
    task = runtime.load_task(task_id)
    
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    return TaskResponse(
        id=task.id,
        status=task.status,
        result=getattr(task, 'result', None),
        error=getattr(task, 'error', None),
    )


@router.get("/{task_id}/status")
async def get_task_status(
    task_id: str,
    runtime: AvatarMain = Depends(get_avatar_runtime),
):
    """
    获取任务状态（用于 WebSocket 重连后的状态同步）
    
    返回：
    - status: running | completed | failed | cancelled
    - progress: 当前进度（已完成步骤数 / 总步骤数）
    - current_step: 当前正在执行的步骤
    - result: 任务结果（如果已完成）
    - error: 错误信息（如果失败）
    """
    task = runtime.load_task(task_id)
    
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    # 计算进度
    total_steps = len(task.steps) if hasattr(task, 'steps') else 0
    completed_steps = sum(1 for step in task.steps if step.status.name == "SUCCESS") if hasattr(task, 'steps') else 0
    
    # 找到当前步骤
    current_step = None
    if hasattr(task, 'steps'):
        for step in task.steps:
            if step.status.name == "RUNNING":
                current_step = {
                    "id": step.id,
                    "skill": step.skill_name,
                    "description": getattr(step, 'description', ''),
                }
                break
    
    return {
        "task_id": task.id,
        "status": task.status.name.lower() if hasattr(task.status, 'name') else str(task.status).lower(),
        "progress": {
            "completed": completed_steps,
            "total": total_steps,
            "percentage": int((completed_steps / total_steps * 100)) if total_steps > 0 else 0,
        },
        "current_step": current_step,
        "result": getattr(task, 'result', None),
        "error": getattr(task, 'error', None),
    }


@router.get("/")
async def list_tasks(
    runtime: AvatarMain = Depends(get_avatar_runtime),
):
    """
    获取任务列表
    
    TODO: 实现任务列表功能
    """
    return {"tasks": [], "message": "任务列表功能待实现"}

