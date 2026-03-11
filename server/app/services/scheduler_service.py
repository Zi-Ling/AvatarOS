# app/services/scheduler_service.py
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session, select
from datetime import datetime
import asyncio

from app.db.database import engine
from app.db.task.schedule import Schedule
from app.core.config import config
from app.io.manager import SocketManager

# 避免循环引用，这里只做类型提示
# from app.avatar.runtime.loop import AgentLoop 

logger = logging.getLogger(__name__)

class SchedulerService:
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.avatar_runtime = None # Replaces agent_loop
        self.main_loop = None # Capture the main event loop

    def start(self, avatar_runtime):
        """
        Start scheduler and load jobs from DB.
        """
        self.avatar_runtime = avatar_runtime
        # Capture the running loop from the runtime context or current context
        try:
            self.main_loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("Scheduler could not capture running loop, attempting fallback")
        
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("📅 Scheduler started")
            
        self._load_jobs_from_db()
    
    def _load_jobs_from_db(self):
        """
        Sync in-memory scheduler with DB
        """
        with Session(engine) as session:
            schedules = session.exec(select(Schedule).where(Schedule.is_active == True)).all()
            for s in schedules:
                self._add_job_to_scheduler(s)
            logger.info(f"📅 Loaded {len(schedules)} active schedules from DB")

    def _add_job_to_scheduler(self, schedule: Schedule):
        """
        Helper to add a job based on Schedule model
        """
        try:
            parts = schedule.cron_expression.split()
            if len(parts) != 5:
                logger.warning(f"Invalid cron expression for schedule {schedule.id}: {schedule.cron_expression}")
                return

            trigger = CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4]
            )

            self.scheduler.add_job(
                func=self.execute_wrapper,
                trigger=trigger,
                args=[schedule.id, schedule.intent_spec],
                id=schedule.id,
                replace_existing=True,
                name=schedule.name
            )

            # 回写 next_run_at
            try:
                job = self.scheduler.get_job(schedule.id)
                if job and job.next_run_time:
                    with Session(engine) as session:
                        s = session.get(Schedule, schedule.id)
                        if s:
                            s.next_run_at = job.next_run_time.replace(tzinfo=None)
                            session.add(s)
                            session.commit()
            except Exception as e:
                logger.warning(f"Failed to update next_run_at for {schedule.id}: {e}")

        except Exception as e:
            logger.error(f"Failed to add job {schedule.id}: {e}")

    def execute_wrapper(self, schedule_id: str, intent_spec: dict):
        """
        Bridge sync scheduler to async agent loop using threadsafe call
        """
        import uuid
        from app.avatar.intent.models import IntentSpec, IntentDomain
        
        try:
            logger.info(f"⏰ Triggering scheduled task: {schedule_id}")
            
            # 🔑 检查任务依赖
            if not self._check_dependencies(schedule_id):
                logger.warning(f"⏸️ Task {schedule_id} skipped due to unmet dependencies")
                return
            
            # Reconstruct Intent
            intent = IntentSpec(
                id=intent_spec.get("metadata", {}).get("intent_id") or str(uuid.uuid4()),
                goal=intent_spec.get("goal", "Scheduled Task"),
                intent_type=intent_spec.get("intent_type", "unknown"),
                domain=IntentDomain(intent_spec.get("domain", "other")),
                raw_user_input=intent_spec.get("goal"), # Fallback
                params={
                    **intent_spec.get("params", {}),
                    "_schedule_id": schedule_id,  # 注入 schedule_id 供依赖检查使用
                }
            )
            
            if self.main_loop and not self.main_loop.is_closed():
                # Submit to the main loop
                future = asyncio.run_coroutine_threadsafe(self.run_async_task(intent), self.main_loop)
                # We don't necessarily need to wait for result, but let's log if submission fails
                # future.result() # This would block until done
            else:
                # Fallback: if no main loop, try running in new loop (risky for DB/Sockets)
                logger.warning("Main loop not available, running task in new loop (DB/Socket issues possible)")
                asyncio.run(self.run_async_task(intent))
            
            # Update Last Run (Sync is fine here as Session is thread-local usually, but better do it in the async task)
            # Actually, let's keep it here for simplicity
            self.update_last_run(schedule_id)
            
        except Exception as e:
            logger.error(f"Scheduled task execution failed: {e}")

    async def run_async_task(self, intent):
        if self.avatar_runtime:
            # AvatarMain.run_intent handles env_context internally
            await self.avatar_runtime.run_intent(intent, task_mode="scheduled")
        else:
            logger.error("AvatarRuntime not initialized in Scheduler")

    def _check_dependencies(self, schedule_id: str) -> bool:
        """
        检查任务依赖是否满足：所有依赖 schedule 的最近一次 Run 必须是 completed
        """
        with Session(engine) as session:
            schedule = session.get(Schedule, schedule_id)
            if not schedule or not schedule.depends_on:
                return True

            from app.db.task.task import Task, Run

            for dep_schedule_id in schedule.depends_on:
                dep_schedule = session.get(Schedule, dep_schedule_id)
                if not dep_schedule:
                    logger.warning(f"Dependency {dep_schedule_id} not found, blocking execution")
                    return False

                # 找到该 schedule 触发的最近一次 Task（task_mode=scheduled，
                # intent_spec 里 metadata.schedule_id 匹配）
                dep_tasks = session.exec(
                    select(Task).where(Task.task_mode == "scheduled")
                ).all()
                dep_task_ids = [
                    t.id for t in dep_tasks
                    if t.intent_spec.get("metadata", {}).get("schedule_id") == dep_schedule_id
                ]

                if not dep_task_ids:
                    logger.info(f"Dependency {dep_schedule_id} has never run")
                    return False

                # 取最近一次 Run
                latest_run = session.exec(
                    select(Run)
                    .where(Run.task_id.in_(dep_task_ids))  # type: ignore[attr-defined]
                    .order_by(Run.created_at.desc())  # type: ignore[attr-defined]
                ).first()

                if not latest_run or latest_run.status != "completed":
                    logger.info(
                        f"Dependency {dep_schedule_id} last run status: "
                        f"{latest_run.status if latest_run else 'none'}"
                    )
                    return False

            return True

    def update_last_run(self, schedule_id: str):
        with Session(engine) as session:
            s = session.get(Schedule, schedule_id)
            if s:
                s.last_run_at = datetime.utcnow()
                session.add(s)
                session.commit()

    def create_schedule(self, name: str, cron: str, intent: dict):
        with Session(engine) as session:
            s = Schedule(
                name=name,
                cron_expression=cron,
                intent_spec=intent,
                is_active=True
            )
            session.add(s)
            session.commit()
            session.refresh(s)

            # 把 schedule_id 写入 intent_spec.metadata，供依赖检查关联 Task
            intent_with_id = {
                **intent,
                "metadata": {**intent.get("metadata", {}), "schedule_id": s.id},
            }
            s.intent_spec = intent_with_id
            session.add(s)
            session.commit()
            session.refresh(s)

            self._add_job_to_scheduler(s)
            self._emit_schedule_event('created', s)
            return s
    
    def _emit_schedule_event(self, event_type: str, schedule: Schedule):
        """推送定时任务事件到前端"""
        try:
            socket_manager = SocketManager.get_instance()
            if self.main_loop and self.main_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    socket_manager.emit("server_event", {
                        "type": f"schedule.{event_type}",
                        "payload": {
                            "id": schedule.id,
                            "name": schedule.name,
                            "cron_expression": schedule.cron_expression,
                            "is_active": schedule.is_active,
                            "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
                        }
                    }),
                    self.main_loop
                )
        except Exception as e:
            logger.error(f"Failed to emit schedule event: {e}")

# Singleton
scheduler_service = SchedulerService()

