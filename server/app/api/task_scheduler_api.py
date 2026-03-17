# server/app/api/task_scheduler_api.py
"""
调度器 API 端点

GET  /scheduler/status — 查询队列状态和槽位使用情况
PUT  /scheduler/config — 更新槽位配置
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scheduler", tags=["scheduler"])

# Module-level scheduler reference — set during app startup
_scheduler = None


def set_scheduler(scheduler) -> None:
    """Set the scheduler instance (called during app startup)."""
    global _scheduler
    _scheduler = scheduler


class SchedulerConfigUpdate(BaseModel):
    long_task_slots: Optional[int] = None
    simple_task_slots: Optional[int] = None


@router.get("/status")
async def get_scheduler_status():
    """GET /scheduler/status — 查询队列状态和槽位使用情况"""
    if _scheduler is None:
        return {
            "running": {"long_task": 0, "simple_task": 0},
            "queue_size": 0,
            "slots": {"long_task": 1, "simple_task": 2},
        }
    return {
        "running": _scheduler.get_running_count(),
        "queue_size": len(_scheduler._queue),
        "slots": {
            "long_task": _scheduler._long_task_slots,
            "simple_task": _scheduler._simple_task_slots,
        },
    }


@router.put("/config")
async def update_scheduler_config(req: SchedulerConfigUpdate):
    """PUT /scheduler/config — 更新槽位配置"""
    if _scheduler is None:
        return {
            "status": "no_scheduler",
            "message": "Scheduler not initialized",
        }

    updated = {}
    if req.long_task_slots is not None:
        _scheduler._long_task_slots = req.long_task_slots
        updated["long_task_slots"] = req.long_task_slots
    if req.simple_task_slots is not None:
        _scheduler._simple_task_slots = req.simple_task_slots
        updated["simple_task_slots"] = req.simple_task_slots

    logger.info(f"[SchedulerAPI] Updated config: {updated}")
    return {
        "status": "updated",
        "config": {
            "long_task_slots": _scheduler._long_task_slots,
            "simple_task_slots": _scheduler._simple_task_slots,
        },
    }
