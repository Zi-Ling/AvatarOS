# app/crud/logging/llm.py
"""
LLM 调用日志存储层

提供便捷的 CRUD 操作接口
"""
from __future__ import annotations

from sqlmodel import Session, select
from typing import Optional, List
from datetime import datetime

from app.db.logging import LLMCall
from app.db.database import engine


class LLMCallStore:
    """LLM 调用日志存储操作"""
    
    @staticmethod
    def create(
        call_id: str,
        source: str = "unknown",
        parent_id: Optional[str] = None,
        model: Optional[str] = None,
        prompt: Optional[str] = None,
        params: Optional[dict] = None,
        db: Optional[Session] = None,
    ) -> LLMCall:
        """
        创建 LLM 调用记录
        
        Args:
            call_id: 调用 ID
            source: 来源（router/planner/skill/other）
            parent_id: 父记录 ID（可选）
            model: 模型名称
            prompt: 提示词
            params: 其他参数
            db: 数据库会话（可选）
        """
        if db is None:
            with Session(engine) as session:
                llm_call = LLMCall(
                    call_id=call_id,
                    source=source,
                    parent_id=parent_id,
                    model=model,
                    prompt=prompt,
                    params=params,
                )
                session.add(llm_call)
                session.commit()
                session.refresh(llm_call)
                return llm_call
        else:
            llm_call = LLMCall(
                call_id=call_id,
                source=source,
                parent_id=parent_id,
                model=model,
                prompt=prompt,
                params=params,
            )
            db.add(llm_call)
            db.commit()
            db.refresh(llm_call)
            return llm_call
    
    @staticmethod
    def update_result(
        llm_call_id: str,
        success: bool,
        response: Optional[str] = None,
        error: Optional[str] = None,
        usage: Optional[dict] = None,
        db: Optional[Session] = None,
    ) -> Optional[LLMCall]:
        """
        更新 LLM 调用结果
        
        Args:
            llm_call_id: LLM 调用记录 ID
            success: 是否成功
            response: 响应内容
            error: 错误信息
            usage: 使用情况
            db: 数据库会话（可选）
        """
        if db is None:
            with Session(engine) as session:
                statement = select(LLMCall).where(LLMCall.id == llm_call_id)
                llm_call = session.exec(statement).first()
                if llm_call:
                    llm_call.success = success
                    llm_call.response = response
                    llm_call.error = error
                    llm_call.usage = usage
                    llm_call.finished_at = datetime.utcnow()
                    
                    # 计算延迟
                    if llm_call.started_at and llm_call.finished_at:
                        delta = llm_call.finished_at - llm_call.started_at
                        llm_call.latency_ms = delta.total_seconds() * 1000
                    
                    session.add(llm_call)
                    session.commit()
                    session.refresh(llm_call)
                return llm_call
        else:
            statement = select(LLMCall).where(LLMCall.id == llm_call_id)
            llm_call = db.exec(statement).first()
            if llm_call:
                llm_call.success = success
                llm_call.response = response
                llm_call.error = error
                llm_call.usage = usage
                llm_call.finished_at = datetime.utcnow()
                
                # 计算延迟
                if llm_call.started_at and llm_call.finished_at:
                    delta = llm_call.finished_at - llm_call.started_at
                    llm_call.latency_ms = delta.total_seconds() * 1000
                
                db.add(llm_call)
                db.commit()
                db.refresh(llm_call)
            return llm_call
    
    @staticmethod
    def get(llm_call_id: str, db: Optional[Session] = None) -> Optional[LLMCall]:
        """根据 ID 获取 LLM 调用记录"""
        if db is None:
            with Session(engine) as session:
                statement = select(LLMCall).where(LLMCall.id == llm_call_id)
                return session.exec(statement).first()
        else:
            statement = select(LLMCall).where(LLMCall.id == llm_call_id)
            return db.exec(statement).first()
    
    @staticmethod
    def list_by_source(
        source: str,
        limit: int = 100,
        db: Optional[Session] = None,
    ) -> List[LLMCall]:
        """列出某来源的所有 LLM 调用"""
        if db is None:
            with Session(engine) as session:
                statement = (
                    select(LLMCall)
                    .where(LLMCall.source == source)
                    .order_by(LLMCall.started_at.desc())
                    .limit(limit)
                )
                return list(session.exec(statement).all())
        else:
            statement = (
                select(LLMCall)
                .where(LLMCall.source == source)
                .order_by(LLMCall.started_at.desc())
                .limit(limit)
            )
            return list(db.exec(statement).all())
    
    @staticmethod
    def list_by_parent(
        parent_id: str,
        limit: int = 100,
        db: Optional[Session] = None,
    ) -> List[LLMCall]:
        """列出某父记录的所有 LLM 调用"""
        if db is None:
            with Session(engine) as session:
                statement = (
                    select(LLMCall)
                    .where(LLMCall.parent_id == parent_id)
                    .order_by(LLMCall.started_at.desc())
                    .limit(limit)
                )
                return list(session.exec(statement).all())
        else:
            statement = (
                select(LLMCall)
                .where(LLMCall.parent_id == parent_id)
                .order_by(LLMCall.started_at.desc())
                .limit(limit)
            )
            return list(db.exec(statement).all())
    
    @staticmethod
    def list_all(limit: int = 100, db: Optional[Session] = None) -> List[LLMCall]:
        """列出所有 LLM 调用"""
        if db is None:
            with Session(engine) as session:
                statement = (
                    select(LLMCall)
                    .order_by(LLMCall.started_at.desc())
                    .limit(limit)
                )
                return list(session.exec(statement).all())
        else:
            statement = (
                select(LLMCall)
                .order_by(LLMCall.started_at.desc())
                .limit(limit)
            )
            return list(db.exec(statement).all())

