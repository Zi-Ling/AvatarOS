# app/api/logging/router.py
"""
日志查询 API
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional, List, Dict, Any

from app.log import LogAggregator
from app.core.dependencies import get_log_aggregator


router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("/requests/{request_id}")
async def get_request_trace(
    request_id: str,
    log_aggregator: LogAggregator = Depends(get_log_aggregator),
) -> Dict[str, Any]:
    """
    获取单次请求的完整轨迹
    
    包含：
    - Router 决策
    - LLM 调用列表
    - Task 执行（如果有）
    """
    trace = log_aggregator.get_request_full_trace(request_id)
    
    if not trace:
        raise HTTPException(status_code=404, detail="Request not found")
    
    # 格式化返回
    return {
        "request_id": trace.request_id,
        "router_log": {
            "created_at": trace.router_log.created_at if trace.router_log else None,
            "decision": {
                "route_type": trace.router_log.decision.route_type if trace.router_log and trace.router_log.decision else None,
                "target": trace.router_log.decision.target if trace.router_log and trace.router_log.decision else None,
                "input_text": trace.router_log.decision.input_text if trace.router_log and trace.router_log.decision else None,
            } if trace.router_log and trace.router_log.decision else None,
        } if trace.router_log else None,
        "llm_calls": [
            {
                "id": call.id,
                "model": call.model,
                "started_at": call.started_at,
                "finished_at": call.finished_at,
                "latency_ms": call.latency_ms,
                "success": call.success,
                "prompt_length": len(call.prompt) if call.prompt else 0,
                "response_length": len(call.response_text) if call.response_text else 0,
            }
            for call in trace.llm_calls
        ],
        "task_execution": {
            "task_id": trace.task_execution.task_id,
            "status": trace.task_execution.status.name if trace.task_execution else None,
            "started_at": trace.task_execution.started_at if trace.task_execution else None,
            "finished_at": trace.task_execution.finished_at if trace.task_execution else None,
            "duration_ms": trace.task_execution.duration_ms if trace.task_execution else None,
            "steps_count": len(trace.task_execution.steps) if trace.task_execution else 0,
        } if trace.task_execution else None,
        "total_duration_ms": trace.total_duration_ms,
    }


@router.get("/tasks/{task_id}/execution")
async def get_task_execution_trace(
    task_id: str,
    log_aggregator: LogAggregator = Depends(get_log_aggregator),
) -> Dict[str, Any]:
    """
    获取任务执行详情
    
    包含所有步骤的执行情况
    """
    trace = log_aggregator.get_task_execution_trace(task_id)
    
    if not trace:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # 格式化返回
    return {
        "task_id": trace.task_id,
        "status": trace.task_log.status.name if trace.task_log else None,
        "started_at": trace.task_log.started_at if trace.task_log else None,
        "finished_at": trace.task_log.finished_at if trace.task_log else None,
        "duration_ms": trace.task_log.duration_ms if trace.task_log else None,
        "steps": [
            {
                "step_id": step.step_id,
                "order": step.order,
                "skill_name": step.skill_name,
                "status": step.status.name,
                "started_at": step.started_at,
                "finished_at": step.finished_at,
                "duration_ms": step.duration_ms,
                "error": step.error,
            }
            for step in (trace.task_log.steps if trace.task_log else [])
        ],
    }


@router.get("/llm-calls")
async def list_llm_calls(
    limit: int = 50,
    source: Optional[str] = None,
    log_aggregator: LogAggregator = Depends(get_log_aggregator),
) -> Dict[str, Any]:
    """
    查询 LLM 调用日志
    
    参数：
    - limit: 返回数量限制
    - source: 来源过滤（router/planner/skill/other）
    """
    calls = log_aggregator.get_recent_llm_calls(limit=limit, source=source)
    
    return {
        "total": len(calls),
        "calls": [
            {
                "id": call.id,
                "call_id": call.call_id,
                "model": call.model,
                "started_at": call.started_at,
                "finished_at": call.finished_at,
                "latency_ms": call.latency_ms,
                "success": call.success,
                "prompt_length": len(call.prompt) if call.prompt else 0,
                "response_length": len(call.response) if isinstance(call.response, str) else 0,
                "error": call.error,
            }
            for call in calls
        ],
    }


@router.get("/router/stats")
async def get_router_stats(
    log_aggregator: LogAggregator = Depends(get_log_aggregator),
) -> Dict[str, Any]:
    """
    Router 统计信息
    
    包含：
    - 各 route_type 占比
    - 平均 LLM 调用次数
    - 成功率
    """
    stats = log_aggregator.get_statistics()
    return stats


@router.get("/requests")
async def list_requests(
    limit: int = 50,
    log_aggregator: LogAggregator = Depends(get_log_aggregator),
) -> Dict[str, Any]:
    """
    查询最近的 Router 请求
    """
    logs = log_aggregator.get_recent_requests(limit=limit)
    
    return {
        "total": len(logs),
        "requests": [
            {
                "request_id": log.request_id,
                "created_at": log.created_at,
                "route_type": log.decision.route_type if log.decision else None,
                "target": log.decision.target if log.decision else None,
                "input_text": log.decision.input_text if log.decision else None,
                "llm_calls_count": len(log.llm_calls),
            }
            for log in logs
        ],
    }


@router.get("/tasks")
async def list_tasks(
    limit: int = 50,
    log_aggregator: LogAggregator = Depends(get_log_aggregator),
) -> Dict[str, Any]:
    """
    查询最近的任务执行
    """
    logs = log_aggregator.get_recent_tasks(limit=limit)
    
    return {
        "total": len(logs),
        "tasks": [
            {
                "task_id": log.task_id,
                "status": log.status.name,
                "started_at": log.started_at,
                "finished_at": log.finished_at,
                "duration_ms": log.duration_ms,
                "steps_count": len(log.steps),
            }
            for log in logs
        ],
    }

