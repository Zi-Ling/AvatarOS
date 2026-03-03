"""
Workflow Scheduler: 定时任务调度器

基于 APScheduler 实现工作流的定时触发
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional
from datetime import datetime

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.date import DateTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.jobstores.memory import MemoryJobStore
    APSCHEDULER_AVAILABLE = True
except ImportError:
    APSCHEDULER_AVAILABLE = False
    AsyncIOScheduler = None
    CronTrigger = None
    DateTrigger = None
    IntervalTrigger = None
    MemoryJobStore = None

from .template import WorkflowTemplate

logger = logging.getLogger(__name__)


class WorkflowScheduler:
    """
    工作流调度器
    
    功能：
    - 定时触发工作流（基于 Cron 表达式）
    - 手动触发工作流
    - 管理调度任务的生命周期
    """
    
    def __init__(self, executor_callback: Optional[Callable] = None):
        """
        初始化调度器
        
        Args:
            executor_callback: 工作流执行回调函数
                签名: async def callback(template_id: str, context: dict) -> Any
        """
        if not APSCHEDULER_AVAILABLE:
            raise ImportError(
                "APScheduler is not installed. "
                "Install it with: pip install apscheduler"
            )
        
        self._scheduler = AsyncIOScheduler(
            jobstores={'default': MemoryJobStore()},
            timezone='Asia/Shanghai'
        )
        
        self._executor_callback = executor_callback
        self._scheduled_workflows: Dict[str, WorkflowTemplate] = {}
        self._running = False
        
        logger.info("WorkflowScheduler initialized")
    
    def start(self) -> None:
        """启动调度器"""
        if not self._running:
            self._scheduler.start()
            self._running = True
            logger.info("WorkflowScheduler started")
    
    def shutdown(self, wait: bool = True) -> None:
        """关闭调度器"""
        if self._running:
            self._scheduler.shutdown(wait=wait)
            self._running = False
            logger.info("WorkflowScheduler shutdown")
    
    def schedule_workflow(
        self,
        template: WorkflowTemplate,
        replace_existing: bool = True
    ) -> bool:
        """
        调度工作流
        
        Args:
            template: 工作流模板
            replace_existing: 如果已存在同ID的任务，是否替换
        
        Returns:
            是否成功调度
        """
        if not template.enabled:
            logger.info(f"Workflow {template.id} is disabled, skipping scheduling")
            return False
        
        if not template.schedule:
            logger.warning(f"Workflow {template.id} has no schedule, skipping")
            return False
        
        # 验证模板
        is_valid, error = template.validate()
        if not is_valid:
            logger.error(f"Invalid workflow template {template.id}: {error}")
            return False
        
        # 创建 Cron trigger
        try:
            trigger = CronTrigger.from_crontab(template.schedule, timezone='Asia/Shanghai')
        except Exception as e:
            logger.error(f"Invalid cron expression for workflow {template.id}: {e}")
            return False
        
        # 添加任务
        try:
            self._scheduler.add_job(
                func=self._execute_workflow_job,
                trigger=trigger,
                args=[template.id, {}],
                id=template.id,
                name=template.name,
                replace_existing=replace_existing,
                misfire_grace_time=300  # 允许5分钟的误差
            )
            
            self._scheduled_workflows[template.id] = template
            logger.info(f"Scheduled workflow: {template.name} ({template.id}) with cron: {template.schedule}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to schedule workflow {template.id}: {e}")
            return False
    
    def schedule_once(
        self,
        template: WorkflowTemplate,
        run_date: datetime,
        context: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        一次性调度工作流
        
        Args:
            template: 工作流模板
            run_date: 执行时间
            context: 执行上下文
        
        Returns:
            是否成功调度
        """
        job_id = f"{template.id}_once_{run_date.timestamp()}"
        
        try:
            trigger = DateTrigger(run_date=run_date, timezone='Asia/Shanghai')
            
            self._scheduler.add_job(
                func=self._execute_workflow_job,
                trigger=trigger,
                args=[template.id, context or {}],
                id=job_id,
                name=f"{template.name} (Once)",
                replace_existing=False
            )
            
            logger.info(f"Scheduled one-time workflow: {template.name} at {run_date}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to schedule one-time workflow {template.id}: {e}")
            return False
    
    def unschedule_workflow(self, template_id: str) -> bool:
        """
        取消调度工作流
        
        Args:
            template_id: 工作流ID
        
        Returns:
            是否成功取消
        """
        try:
            self._scheduler.remove_job(template_id)
            
            if template_id in self._scheduled_workflows:
                del self._scheduled_workflows[template_id]
            
            logger.info(f"Unscheduled workflow: {template_id}")
            return True
            
        except Exception as e:
            logger.warning(f"Failed to unschedule workflow {template_id}: {e}")
            return False
    
    async def trigger_workflow(
        self,
        template_id: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        手动触发工作流（立即执行）
        
        Args:
            template_id: 工作流ID
            context: 执行上下文
        
        Returns:
            执行结果
        """
        logger.info(f"Manually triggering workflow: {template_id}")
        
        if self._executor_callback:
            return await self._executor_callback(template_id, context or {})
        else:
            logger.error("No executor callback configured")
            return None
    
    async def _execute_workflow_job(
        self,
        template_id: str,
        context: Dict[str, Any]
    ) -> None:
        """
        执行工作流任务（由调度器调用）
        """
        logger.info(f"Scheduled execution triggered for workflow: {template_id}")
        
        try:
            if self._executor_callback:
                await self._executor_callback(template_id, context)
            else:
                logger.error("No executor callback configured")
        except Exception as e:
            logger.error(f"Error executing workflow {template_id}: {e}", exc_info=True)
    
    def get_next_run_time(self, template_id: str) -> Optional[datetime]:
        """
        获取工作流的下次执行时间
        
        Args:
            template_id: 工作流ID
        
        Returns:
            下次执行时间，如果未调度则返回 None
        """
        try:
            job = self._scheduler.get_job(template_id)
            if job:
                return job.next_run_time
        except Exception:
            pass
        
        return None
    
    def list_scheduled_workflows(self) -> Dict[str, Dict[str, Any]]:
        """
        列出所有已调度的工作流
        
        Returns:
            {workflow_id: {template, next_run_time}}
        """
        result = {}
        
        for template_id, template in self._scheduled_workflows.items():
            next_run_time = self.get_next_run_time(template_id)
            
            result[template_id] = {
                "template": template,
                "next_run_time": next_run_time.isoformat() if next_run_time else None,
                "enabled": template.enabled
            }
        
        return result
    
    def is_running(self) -> bool:
        """调度器是否正在运行"""
        return self._running
    
    def get_job_info(self, template_id: str) -> Optional[Dict[str, Any]]:
        """
        获取调度任务的详细信息
        
        Args:
            template_id: 工作流ID
        
        Returns:
            任务信息字典，如果不存在则返回 None
        """
        try:
            job = self._scheduler.get_job(template_id)
            if job:
                return {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                    "trigger": str(job.trigger)
                }
        except Exception as e:
            logger.error(f"Failed to get job info for {template_id}: {e}")
        
        return None


# 全局调度器实例（可选）
_global_scheduler: Optional[WorkflowScheduler] = None


def get_global_scheduler() -> Optional[WorkflowScheduler]:
    """获取全局调度器实例"""
    return _global_scheduler


def set_global_scheduler(scheduler: WorkflowScheduler) -> None:
    """设置全局调度器实例"""
    global _global_scheduler
    _global_scheduler = scheduler























