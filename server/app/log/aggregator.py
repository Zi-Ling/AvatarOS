# app/logging/aggregator.py
"""
日志聚合器

统一管理三层日志（Router、LLM、Runtime），提供关联查询接口
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime

from app.router.logging import RouterLogger, RouterRequestLog
from app.llm.logging import LLMLogger, LLMCallLogRecord
from app.avatar.runtime.monitoring import StepLogger, TaskLog


@dataclass
class RequestTrace:
    """
    完整的请求轨迹
    
    包含一次用户请求的完整生命周期：
    - Router 决策
    - LLM 调用
    - Task 执行（如果有）
    """
    request_id: str
    router_log: Optional[RouterRequestLog] = None
    llm_calls: List[LLMCallLogRecord] = field(default_factory=list)
    task_execution: Optional[TaskLog] = None
    
    @property
    def total_duration_ms(self) -> Optional[float]:
        """计算总耗时（毫秒）"""
        if not self.router_log:
            return None
        
        start_time = self.router_log.created_at
        
        # 找最晚的结束时间
        end_time = start_time
        
        # 检查 LLM 调用
        for llm_call in self.llm_calls:
            if llm_call.finished_at and llm_call.finished_at > end_time:
                end_time = llm_call.finished_at
        
        # 检查 Task 执行
        if self.task_execution and self.task_execution.finished_at:
            if self.task_execution.finished_at > end_time:
                end_time = self.task_execution.finished_at
        
        return (end_time - start_time) * 1000


@dataclass
class TaskTrace:
    """
    任务执行轨迹
    
    包含任务执行的详细信息和关联的 LLM 调用
    """
    task_id: str
    task_log: Optional[TaskLog] = None
    llm_calls_by_step: Dict[str, List[LLMCallLogRecord]] = field(default_factory=dict)


class LogAggregator:
    """
    统一日志聚合器
    
    关联三层日志，提供统一查询接口
    """
    
    def __init__(
        self,
        router_logger: RouterLogger,
        llm_logger: LLMLogger,
        runtime_logger: StepLogger,
    ):
        self._router_logger = router_logger
        self._llm_logger = llm_logger
        self._runtime_logger = runtime_logger
    
    def get_request_full_trace(self, request_id: str) -> Optional[RequestTrace]:
        """
        获取一次请求的完整轨迹
        
        Args:
            request_id: 请求 ID
        
        Returns:
            RequestTrace: 完整轨迹，如果不存在则返回 None
        """
        # 获取 Router 日志
        router_log = self._router_logger.get_request_log(request_id)
        if not router_log:
            return None
        
        # 提取 LLM 调用（Router 层的）
        llm_calls = router_log.llm_calls if router_log.llm_calls else []
        
        # 如果路由到了任务，获取任务执行日志
        task_execution = None
        if router_log.decision and router_log.decision.meta:
            task_id = router_log.decision.meta.get("task_id")
            if task_id:
                task_execution = self._runtime_logger.get_task_log(task_id)
        
        return RequestTrace(
            request_id=request_id,
            router_log=router_log,
            llm_calls=llm_calls,
            task_execution=task_execution,
        )
    
    def get_task_execution_trace(self, task_id: str) -> Optional[TaskTrace]:
        """
        获取任务执行的完整轨迹
        
        Args:
            task_id: 任务 ID（实际上是 run_id）
        
        Returns:
            TaskTrace: 任务轨迹，如果不存在则返回 None
        """
        # 获取任务日志
        task_log = self._runtime_logger.get_task_log(task_id)
        if not task_log:
            return None
        
        # 这里可以扩展：获取每个步骤的 LLM 调用
        # 目前由于 Step 不直接调用 LLM，所以暂时为空
        llm_calls_by_step = {}
        
        return TaskTrace(
            task_id=task_id,
            task_log=task_log,
            llm_calls_by_step=llm_calls_by_step,
        )
    
    def get_recent_requests(self, limit: int = 50) -> List[RouterRequestLog]:
        """
        获取最近的请求日志
        
        Args:
            limit: 返回数量限制
        
        Returns:
            List[RouterRequestLog]: 请求日志列表
        """
        all_logs = self._router_logger.get_all_request_logs()
        return all_logs[:limit]
    
    def get_recent_llm_calls(
        self,
        limit: int = 50,
        source: Optional[str] = None,
    ) -> List[LLMCallLogRecord]:
        """
        获取最近的 LLM 调用
        
        Args:
            limit: 返回数量限制
            source: 来源过滤（router/planner/skill/other）
        
        Returns:
            List[LLMCallLogRecord]: LLM 调用日志列表
        """
        # 这个方法需要 LLMLogger 支持过滤，目前返回全部
        all_logs = self._llm_logger.get_all_logs()
        return all_logs[:limit]
    
    def get_recent_tasks(self, limit: int = 50) -> List[TaskLog]:
        """
        获取最近的任务执行日志
        
        Args:
            limit: 返回数量限制
        
        Returns:
            List[TaskLog]: 任务日志列表
        """
        all_logs = self._runtime_logger.get_all_task_logs()
        return all_logs[:limit]
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        获取日志统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        # 获取基础数据
        router_logs = self._router_logger.get_all_request_logs()
        llm_logs = self._llm_logger.get_all_logs()
        task_logs = self._runtime_logger.get_all_task_logs()
        
        # 统计路由类型
        route_types = {}
        for log in router_logs:
            if log.decision:
                rt = log.decision.route_type or "unknown"
                route_types[rt] = route_types.get(rt, 0) + 1
        
        # 统计 LLM 成功率
        llm_total = len(llm_logs)
        llm_success = sum(1 for log in llm_logs if log.success)
        
        # 统计任务成功率
        from app.avatar.planner.models import TaskStatus
        task_total = len(task_logs)
        task_success = sum(1 for log in task_logs if log.status == TaskStatus.SUCCESS)
        
        # 计算平均 LLM 延迟
        llm_latencies = [log.latency_ms for log in llm_logs if log.latency_ms]
        avg_llm_latency = sum(llm_latencies) / len(llm_latencies) if llm_latencies else 0
        
        return {
            "router": {
                "total_requests": len(router_logs),
                "route_types": route_types,
            },
            "llm": {
                "total_calls": llm_total,
                "success_count": llm_success,
                "success_rate": llm_success / llm_total if llm_total > 0 else 0,
                "avg_latency_ms": round(avg_llm_latency, 2),
            },
            "tasks": {
                "total_runs": task_total,
                "success_count": task_success,
                "success_rate": task_success / task_total if task_total > 0 else 0,
            },
        }

