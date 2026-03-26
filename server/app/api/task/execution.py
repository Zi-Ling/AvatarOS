# app/api/task/execution.py
"""
Task 执行记录 API（Task/Run/Step）
"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session

from app.db import get_db, TaskStore, RunStore, StepStore
from app.api.task.models import TaskListResponse, TaskDetailResponse, TaskListItemResponse, RunResponse, StepResponse

logger = logging.getLogger(__name__)

router = APIRouter()


# ============ Task API ============

@router.get("/", response_model=TaskListResponse)
def list_tasks(
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """
    获取任务列表
    """
    tasks = TaskStore.list_all(limit=limit, db=db)
    
    # 转换为响应格式
    task_items = []
    for task in tasks:
        # 获取最后一次运行的状态
        runs = RunStore.list_by_task(task.id, limit=1, db=db)
        last_run_status = runs[0].status if runs else None
        run_count = len(RunStore.list_by_task(task.id, limit=1000, db=db))
        
        task_items.append(
            TaskListItemResponse(
                id=task.id,
                title=task.title,
                task_mode=task.task_mode,
                created_at=task.created_at.isoformat(),
                last_run_status=last_run_status,
                run_count=run_count,
            )
        )
    
    return TaskListResponse(
        tasks=task_items,
        total=len(task_items),
    )


@router.get("/{task_id}", response_model=TaskDetailResponse)
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
):
    """
    获取任务详情（包含所有运行记录）
    """
    task = TaskStore.get(task_id, db=db)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # 获取所有运行记录
    runs = RunStore.list_by_task(task.id, limit=50, db=db)
    
    run_responses = []
    for run in runs:
        # 获取步骤
        steps = StepStore.list_by_run(run.id, db=db)
        
        step_responses = [
            StepResponse(
                id=step.id,
                step_index=step.step_index,
                step_name=step.step_name,
                skill_name=step.skill_name,
                status=step.status,
                input_params=step.input_params,
                output_result=step.output_result,
                error_message=step.error_message,
                started_at=step.started_at.isoformat() if step.started_at else None,
                finished_at=step.finished_at.isoformat() if step.finished_at else None,
                duration_ms=step.duration_ms,
            )
            for step in steps
        ]
        
        run_responses.append(
            RunResponse(
                id=run.id,
                task_id=run.task_id,
                status=run.status,
                summary=run.summary,
                error_message=run.error_message,
                created_at=run.created_at.isoformat(),
                started_at=run.started_at.isoformat() if run.started_at else None,
                finished_at=run.finished_at.isoformat() if run.finished_at else None,
                duration_seconds=run.duration_seconds,
                steps=step_responses,
            )
        )
    
    return TaskDetailResponse(
        id=task.id,
        title=task.title,
        intent_spec=task.intent_spec,
        task_mode=task.task_mode,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(),
        runs=run_responses,
    )


@router.delete("/{task_id}")
def delete_task(
    task_id: str,
    db: Session = Depends(get_db),
):
    """
    删除任务（及其所有运行记录）
    """
    success = TaskStore.delete(task_id, db=db)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found")

    return {"message": "Task deleted successfully"}


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str):
    """取消正在执行的任务。幂等：任务不存在或已结束时返回 accepted=false。"""
    from app.api.chat.cancellation import get_cancellation_manager
    from app.io.manager import SocketManager
    mgr = get_cancellation_manager()
    accepted, prev_status, curr_status = mgr.cancel_task(task_id)
    if prev_status == "unknown":
        raise HTTPException(status_code=404, detail="Task not found or already finished")
    if accepted:
        socket_manager = SocketManager.get_instance()
        await socket_manager.emit("server_event", {
            "type": "task_status_changed",
            "payload": {
                "task_id": task_id,
                "previous_status": prev_status,
                "current_status": curr_status,
            },
        })
    return {
        "task_id": task_id,
        "accepted": accepted,
        "previous_status": prev_status,
        "current_status": curr_status,
    }


@router.post("/{task_id}/pause")
async def pause_task(task_id: str):
    """暂停正在执行的任务。幂等：已暂停时返回 accepted=false。"""
    from app.api.chat.cancellation import get_cancellation_manager
    from app.io.manager import SocketManager
    mgr = get_cancellation_manager()
    accepted, prev_status, curr_status = mgr.pause_task(task_id)
    if prev_status == "unknown":
        raise HTTPException(status_code=404, detail="Task not found or already finished")
    if accepted:
        # 写入暂停上下文（Continuity Card 数据源）
        try:
            import json
            from app.services.task_session_store import TaskSessionStore
            from app.db.database import engine as db_engine
            from sqlmodel import Session as DBSession, select
            from app.db.long_task_models import TaskSession, StepState

            with DBSession(db_engine) as db:
                ts = db.exec(select(TaskSession).where(TaskSession.id == task_id)).first()
                if ts:
                    # 收集已完成步骤摘要
                    completed_steps = db.exec(
                        select(StepState).where(
                            StepState.task_session_id == task_id,
                            StepState.status == "success",
                        )
                    ).all()
                    completed_summary = [s.capability_name for s in completed_steps[:10]]

                    # 查找下一个 pending/ready 步骤
                    next_step = db.exec(
                        select(StepState).where(
                            StepState.task_session_id == task_id,
                            StepState.status.in_(["pending", "ready"]),
                        ).limit(1)
                    ).first()

                    pause_ctx = {
                        "pause_reason": "用户主动暂停",
                        "completed_steps_summary": completed_summary,
                        "completed_count": len(completed_steps),
                        "next_planned_action": next_step.capability_name if next_step else None,
                    }
                    ts.pause_context_json = json.dumps(pause_ctx, ensure_ascii=False)
                    db.add(ts)
                    db.commit()
        except Exception as e:
            logger.warning(f"[pause_task] Failed to write pause context: {e}")

        socket_manager = SocketManager.get_instance()
        await socket_manager.emit("server_event", {
            "type": "task_status_changed",
            "payload": {
                "task_id": task_id,
                "previous_status": prev_status,
                "current_status": curr_status,
            },
        })
    return {
        "task_id": task_id,
        "accepted": accepted,
        "previous_status": prev_status,
        "current_status": curr_status,
    }


@router.post("/{task_id}/resume")
async def resume_task(task_id: str):
    """恢复已暂停的任务。幂等：非暂停状态时返回 accepted=false。"""
    from app.api.chat.cancellation import get_cancellation_manager
    from app.io.manager import SocketManager
    mgr = get_cancellation_manager()
    accepted, prev_status, curr_status = mgr.resume_task(task_id)
    if prev_status == "unknown":
        raise HTTPException(status_code=404, detail="Task not found or already finished")
    if accepted:
        # 清除暂停上下文
        try:
            from app.db.database import engine as db_engine
            from sqlmodel import Session as DBSession, select
            from app.db.long_task_models import TaskSession
            with DBSession(db_engine) as db:
                ts = db.exec(select(TaskSession).where(TaskSession.id == task_id)).first()
                if ts:
                    ts.pause_context_json = None
                    db.add(ts)
                    db.commit()
        except Exception:
            pass

        socket_manager = SocketManager.get_instance()
        await socket_manager.emit("server_event", {
            "type": "task_status_changed",
            "payload": {
                "task_id": task_id,
                "previous_status": prev_status,
                "current_status": curr_status,
            },
        })
        # 通过 RecoveryEngine 从 Checkpoint 恢复执行
        try:
            from app.services.recovery_engine import RecoveryEngine
            engine = RecoveryEngine()
            await engine.resume_from_pause(task_id)
        except Exception as e:
            logger.warning(f"[resume_task] RecoveryEngine resume failed (non-fatal): {e}")
    return {
        "task_id": task_id,
        "accepted": accepted,
        "previous_status": prev_status,
        "current_status": curr_status,
    }


@router.get("/{task_id}/pause-context")
async def get_pause_context(task_id: str):
    """获取任务暂停上下文（Continuity Card 数据源）。"""
    import json
    from app.db.database import engine as db_engine
    from sqlmodel import Session as DBSession, select
    from app.db.long_task_models import TaskSession

    with DBSession(db_engine) as db:
        ts = db.exec(select(TaskSession).where(TaskSession.id == task_id)).first()
        if not ts:
            raise HTTPException(status_code=404, detail="Task session not found")
        ctx = json.loads(ts.pause_context_json) if ts.pause_context_json else None
    return {"task_id": task_id, "pause_context": ctx}


# ============ Run API ============

@router.get("/runs/{run_id}", response_model=RunResponse)
def get_run(
    run_id: str,
    db: Session = Depends(get_db),
):
    """
    获取运行详情（包含所有步骤）
    """
    run = RunStore.get(run_id, db=db)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    
    # 获取步骤
    steps = StepStore.list_by_run(run.id, db=db)
    
    step_responses = [
        StepResponse(
            id=step.id,
            step_index=step.step_index,
            step_name=step.step_name,
            skill_name=step.skill_name,
            status=step.status,
            input_params=step.input_params,
            output_result=step.output_result,
            error_message=step.error_message,
            started_at=step.started_at.isoformat() if step.started_at else None,
            finished_at=step.finished_at.isoformat() if step.finished_at else None,
            duration_ms=step.duration_ms,
        )
        for step in steps
    ]
    
    return RunResponse(
        id=run.id,
        task_id=run.task_id,
        status=run.status,
        summary=run.summary,
        error_message=run.error_message,
        created_at=run.created_at.isoformat(),
        started_at=run.started_at.isoformat() if run.started_at else None,
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
        duration_seconds=run.duration_seconds,
        steps=step_responses,
    )

