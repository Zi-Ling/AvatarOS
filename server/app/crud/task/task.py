# app/crud/task/task.py
"""
Task / Run / Step 存储层

提供便捷的 CRUD 操作接口
"""
from __future__ import annotations

from sqlmodel import Session, select
from sqlalchemy.orm import selectinload
from typing import Optional, List
from datetime import datetime, timezone

from app.db.task.task import Task, Run, Step
from app.db.database import engine
from app.avatar.intent import IntentSpec


class TaskStore:
    """Task 存储操作"""
    
    @staticmethod
    def create(
        intent_spec: IntentSpec,
        task_mode: str = "one_shot",
        db: Optional[Session] = None,
    ) -> Task:
        """
        创建任务
        
        Args:
            intent_spec: 意图规格
            task_mode: 任务模式
            db: 数据库会话（可选）
        """
        # V2 IntentSpec serialization
        # Handle Enum serialization manually if to_dict doesn't
        if hasattr(intent_spec, "to_dict"):
            intent_data = intent_spec.to_dict()
        else:
            intent_data = intent_spec.__dict__.copy()
        
        # Serialize Enums
        for k, v in intent_data.items():
            if hasattr(v, "value"): # Enum handling
                intent_data[k] = v.value
        
        # Ensure title fallback
        title = intent_spec.goal or "未命名任务"
        
        if db is None:
            with Session(engine) as session:
                task = Task(
                    title=title,
                    intent_spec=intent_data,
                    task_mode=task_mode,
                )
                
                session.add(task)
                session.commit()
                session.refresh(task)
                
                return task
        else:
            task = Task(
                title=title,
                intent_spec=intent_data,
                task_mode=task_mode,
            )
            
            db.add(task)
            db.commit()
            db.refresh(task)
            
            return task
    
    @staticmethod
    def get(task_id: str, db: Optional[Session] = None) -> Optional[Task]:
        """根据 ID 获取任务"""
        # Preload runs to avoid Lazy Load errors
        statement = select(Task).where(Task.id == task_id).options(selectinload(Task.runs))
        
        if db is None:
            with Session(engine) as session:
                return session.exec(statement).first()
        else:
            return db.exec(statement).first()
    
    @staticmethod
    def list_all(limit: int = 100, db: Optional[Session] = None) -> List[Task]:
        """列出所有任务"""
        statement = select(Task).order_by(Task.created_at.desc()).limit(limit) # List typically doesn't need deep relations
        
        if db is None:
            with Session(engine) as session:
                return list(session.exec(statement).all())
        else:
            return list(db.exec(statement).all())
    
    @staticmethod
    def delete(task_id: str, db: Optional[Session] = None) -> bool:
        """删除任务"""
        if db is None:
            with Session(engine) as session:
                statement = select(Task).where(Task.id == task_id)
                task = session.exec(statement).first()
                if task:
                    session.delete(task)
                    session.commit()
                    return True
                return False
        else:
            statement = select(Task).where(Task.id == task_id)
            task = db.exec(statement).first()
            if task:
                db.delete(task)
                db.commit()
                return True
            return False


class RunStore:
    """Run 存储操作"""
    
    @staticmethod
    def create(task_id: str, db: Optional[Session] = None) -> Run:
        """创建运行记录"""
        run = Run(task_id=task_id, status="pending")
        
        if db is None:
            with Session(engine) as session:
                session.add(run)
                session.commit()
                session.refresh(run)
                return run
        else:
            db.add(run)
            db.commit()
            db.refresh(run)
            return run
    
    @staticmethod
    def get(run_id: str, db: Optional[Session] = None) -> Optional[Run]:
        """根据 ID 获取运行记录"""
        # Explicitly load 'steps' to prevent Lazy Load errors when session closes
        statement = select(Run).where(Run.id == run_id).options(selectinload(Run.steps))
        
        if db is None:
            with Session(engine) as session:
                return session.exec(statement).first()
        else:
            return db.exec(statement).first()
    
    @staticmethod
    def list_by_task(task_id: str, limit: int = 50, db: Optional[Session] = None) -> List[Run]:
        """列出某任务的所有运行"""
        statement = (
            select(Run)
            .where(Run.task_id == task_id)
            .order_by(Run.created_at.desc())
            .limit(limit)
            # Generally we don't load steps for list view to save perf
        )
        
        if db is None:
            with Session(engine) as session:
                return list(session.exec(statement).all())
        else:
            return list(db.exec(statement).all())
    
    @staticmethod
    def update_status(
        run_id: str,
        status: str,
        summary: Optional[str] = None,
        error_message: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Optional[Run]:
        """更新运行状态"""
        if db is None:
            with Session(engine) as session:
                statement = select(Run).where(Run.id == run_id)
                run = session.exec(statement).first()
                if run:
                    run.status = status
                    run.finished_at = datetime.now(timezone.utc) if status in ["completed", "failed"] else None
                    if summary:
                        run.summary = summary
                    if error_message:
                        run.error_message = error_message
                    
                    session.add(run)
                    session.commit()
                    session.refresh(run)
                return run
        else:
            statement = select(Run).where(Run.id == run_id)
            run = db.exec(statement).first()
            if run:
                run.status = status
                run.finished_at = datetime.now(timezone.utc) if status in ["completed", "failed"] else None
                if summary:
                    run.summary = summary
                if error_message:
                    run.error_message = error_message
                
                db.add(run)
                db.commit()
                db.refresh(run)
            return run


class StepStore:
    """Step 存储操作"""
    
    @staticmethod
    def create(
        run_id: str,
        step_index: int,
        step_name: str,
        skill_name: str,
        input_params: dict,
        db: Optional[Session] = None,
    ) -> Step:
        """创建步骤记录"""
        step = Step(
            run_id=run_id,
            step_index=step_index,
            step_name=step_name,
            skill_name=skill_name,
            input_params=input_params,
            status="pending",
        )
        
        if db is None:
            with Session(engine) as session:
                session.add(step)
                session.commit()
                session.refresh(step)
                return step
        else:
            db.add(step)
            db.commit()
            db.refresh(step)
            return step
    
    @staticmethod
    def update_status(
        step_id: str,
        status: str,
        output_result: Optional[dict] = None,
        error_message: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Optional[Step]:
        """更新步骤状态"""
        finished_at = datetime.now(timezone.utc) if status in ["completed", "failed"] else None
        
        if db is None:
            with Session(engine) as session:
                statement = select(Step).where(Step.id == step_id)
                step = session.exec(statement).first()
                if step:
                    step.status = status
                    if finished_at:
                        step.finished_at = finished_at
                    if output_result:
                        step.output_result = output_result
                    if error_message:
                        step.error_message = error_message
                    
                    session.add(step)
                    session.commit()
                    session.refresh(step)
                return step
        else:
            statement = select(Step).where(Step.id == step_id)
            step = db.exec(statement).first()
            if step:
                step.status = status
                if finished_at:
                    step.finished_at = finished_at
                if output_result:
                    step.output_result = output_result
                if error_message:
                    step.error_message = error_message
                
                db.add(step)
                db.commit()
                db.refresh(step)
            return step
