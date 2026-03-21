# app/services/task_service.py
from sqlmodel import Session, select
from datetime import datetime
from typing import Optional, List, Dict, Any
import logging

from app.db.database import engine
from app.db.task.task import Task, Run, Step
from app.avatar.planner.models import Task as RuntimeTask
from app.avatar.planner.models import Step as RuntimeStep
from app.db.serialization import serialize_for_db

logger = logging.getLogger(__name__)

class TaskService:
    """
    Service for managing Task History persistence.
    Decouples Runtime from DB access.
    """
    
    def create_task_from_runtime(self, runtime_task: RuntimeTask) -> Task:
        """
        Initial save of a new Task + Run + Steps plan.
        
        使用通用序列化器确保所有数据都是 JSON-safe 的。
        """
        with Session(engine) as session:
            # 1. Create Task Record
            db_task = Task(
                id=runtime_task.metadata.get("intent_id") or runtime_task.id,
                title=runtime_task.goal[:100], # Truncate title if too long
                intent_spec=serialize_for_db({
                    "goal": runtime_task.goal,
                    "metadata": {
                        k: v for k, v in runtime_task.metadata.items()
                        if not k.startswith("_")
                    }
                }),
                task_mode=runtime_task.metadata.get("task_mode", "one_shot"),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            session.add(db_task)
            
            # 2. Create Initial Run Record
            db_run = Run(
                task_id=db_task.id,
                status="pending",
                created_at=datetime.utcnow(),
                started_at=datetime.utcnow() # Considering creation as start
            )
            session.add(db_run)
            session.flush() # Get db_run.id

            # 3. Create Steps
            for i, step in enumerate(runtime_task.steps):
                db_step = Step(
                    id=step.id,
                    run_id=db_run.id,
                    step_index=i,
                    step_name=step.id,
                    skill_name=step.skill_name,
                    status=step.status.name.lower(), # Convert enum to string
                    input_params=serialize_for_db(step.params),  # 序列化参数
                    created_at=datetime.utcnow()
                )
                session.add(db_step)
            
            session.commit()
            session.refresh(db_task)
            logger.info(f"Persisted new Task {db_task.id} with {len(runtime_task.steps)} steps")
            return db_task

    def update_step_status(self, step_id: str, status: str, result: Dict[str, Any] = None, error: str = None):
        """
        Update a single step's status and result.
        
        使用通用序列化器确保所有数据都是 JSON-safe 的。
        """
        try:
            with Session(engine) as session:
                step = session.get(Step, step_id)
                if not step:
                    logger.warning(f"TaskService: Step {step_id} not found for update")
                    return
                
                step.status = status.lower()
                if result:
                    # 通用序列化：处理 datetime, Pydantic, dataclass 等
                    step.output_result = serialize_for_db(result)
                if error:
                    step.error_message = error
                
                if status.lower() == "running" and not step.started_at:
                    step.started_at = datetime.utcnow()
                
                if status.lower() in ["completed", "failed", "skipped"] and not step.finished_at:
                    step.finished_at = datetime.utcnow()
                    
                session.add(step)
                session.commit()
        except Exception as e:
            logger.error(f"Failed to update step {step_id}: {e}", exc_info=True)

    def persist_replan_steps(self, task_id: str, new_steps: list):
        """
        Replan 成功后，将新步骤持久化到 DB（追加到最新 Run）。
        只插入 DB 中不存在的步骤，避免重复。
        """
        try:
            with Session(engine) as session:
                # 找最新 Run
                run_stmt = select(Run).where(Run.task_id == task_id).order_by(Run.created_at.desc())
                run = session.exec(run_stmt).first()
                if not run:
                    logger.warning(f"TaskService: No run found for task {task_id}, skipping replan step persist")
                    return

                # 查已有 step IDs
                existing_ids_stmt = select(Step.id).where(Step.run_id == run.id)
                existing_ids = set(session.exec(existing_ids_stmt).all())

                # 当前最大 step_index
                max_idx_stmt = select(Step.step_index).where(Step.run_id == run.id).order_by(Step.step_index.desc())
                max_idx_row = session.exec(max_idx_stmt).first()
                next_index = (max_idx_row + 1) if max_idx_row is not None else 0

                added = 0
                for step in new_steps:
                    step_id = getattr(step, "id", None)
                    if not step_id or step_id in existing_ids:
                        continue
                    db_step = Step(
                        id=step_id,
                        run_id=run.id,
                        step_index=next_index,
                        step_name=step_id,
                        skill_name=getattr(step, "skill_name", ""),
                        status="pending",
                        input_params=serialize_for_db(getattr(step, "params", {})),
                        created_at=datetime.utcnow(),
                    )
                    session.add(db_step)
                    existing_ids.add(step_id)
                    next_index += 1
                    added += 1

                session.commit()
                if added:
                    logger.debug(f"TaskService: Persisted {added} replan step(s) for task {task_id}")
        except Exception as e:
            logger.error(f"Failed to persist replan steps for task {task_id}: {e}", exc_info=True)

    def add_step_to_task(self, task_id: str, step: RuntimeStep):
        """
        ReAct 模式：动态添加单个步骤到任务的最新 Run。
        """
        try:
            with Session(engine) as session:
                # 找最新 Run
                run_stmt = select(Run).where(Run.task_id == task_id).order_by(Run.created_at.desc())
                run = session.exec(run_stmt).first()
                if not run:
                    logger.warning(f"TaskService: No run found for task {task_id}, skipping step add")
                    return

                # 检查步骤是否已存在
                existing_step = session.get(Step, step.id)
                if existing_step:
                    logger.debug(f"TaskService: Step {step.id} already exists, skipping")
                    return

                # 获取当前最大 step_index
                max_idx_stmt = select(Step.step_index).where(Step.run_id == run.id).order_by(Step.step_index.desc())
                max_idx_row = session.exec(max_idx_stmt).first()
                next_index = (max_idx_row + 1) if max_idx_row is not None else 0

                # 创建新步骤
                db_step = Step(
                    id=step.id,
                    run_id=run.id,
                    step_index=next_index,
                    step_name=step.id,
                    skill_name=step.skill_name,
                    status="pending",
                    input_params=serialize_for_db(step.params),
                    created_at=datetime.utcnow(),
                )
                session.add(db_step)
                session.commit()
                logger.debug(f"TaskService: Added step {step.id} to task {task_id}")
        except Exception as e:
            logger.error(f"Failed to add step {step.id} to task {task_id}: {e}", exc_info=True)

    def complete_run(self, task_id: str, status: str, error: str = None):
        """
        Mark the latest run of a task as completed/failed.
        """
        try:
            with Session(engine) as session:
                # Find latest run for task
                statement = select(Run).where(Run.task_id == task_id).order_by(Run.created_at.desc())
                run = session.exec(statement).first()
                
                if run:
                    run.status = status.lower()
                    run.finished_at = datetime.utcnow()
                    if error:
                        run.error_message = error
                    session.add(run)
                    session.commit()
        except Exception as e:
            logger.error(f"Failed to complete run for task {task_id}: {e}")

    def get_recent_tasks(self, limit: int = 20) -> List[Task]:
        with Session(engine) as session:
            statement = select(Task).order_by(Task.updated_at.desc()).limit(limit)
            return session.exec(statement).all()

# Global Singleton (Optional, or instantiate where needed)
task_service = TaskService()

