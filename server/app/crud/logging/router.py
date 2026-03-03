# app/crud/logging/router.py
"""
Router 请求日志存储层

提供便捷的 CRUD 操作接口
"""
from __future__ import annotations

from sqlmodel import Session, select
from typing import Optional, List
from datetime import datetime

from app.db.logging import RouterRequest
from app.db.database import engine


class RouterRequestStore:
    """Router 请求日志存储操作"""
    
    @staticmethod
    def create(
        request_id: str,
        input_text: str,
        meta: Optional[dict] = None,
        db: Optional[Session] = None,
    ) -> RouterRequest:
        """
        创建 Router 请求记录
        
        Args:
            request_id: 请求 ID
            input_text: 用户输入
            meta: 元数据
            db: 数据库会话（可选）
        """
        if db is None:
            with Session(engine) as session:
                request = RouterRequest(
                    request_id=request_id,
                    input_text=input_text,
                    meta=meta,
                )
                session.add(request)
                session.commit()
                session.refresh(request)
                return request
        else:
            request = RouterRequest(
                request_id=request_id,
                input_text=input_text,
                meta=meta,
            )
            db.add(request)
            db.commit()
            db.refresh(request)
            return request
    
    @staticmethod
    def update_decision(
        request_id: str,
        route_type: str,
        target: Optional[str] = None,
        intent_spec: Optional[dict] = None,
        task_id: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Optional[RouterRequest]:
        """
        更新 Router 决策信息
        
        Args:
            request_id: 请求 ID
            route_type: 路由类型
            target: 目标
            intent_spec: 意图规格
            task_id: 任务 ID（如果有）
            db: 数据库会话（可选）
        """
        if db is None:
            with Session(engine) as session:
                statement = select(RouterRequest).where(RouterRequest.request_id == request_id)
                request = session.exec(statement).first()
                if request:
                    request.route_type = route_type
                    request.target = target
                    request.intent_spec = intent_spec
                    request.task_id = task_id
                    request.finished_at = datetime.utcnow()
                    
                    session.add(request)
                    session.commit()
                    session.refresh(request)
                return request
        else:
            statement = select(RouterRequest).where(RouterRequest.request_id == request_id)
            request = db.exec(statement).first()
            if request:
                request.route_type = route_type
                request.target = target
                request.intent_spec = intent_spec
                request.task_id = task_id
                request.finished_at = datetime.utcnow()
                
                db.add(request)
                db.commit()
                db.refresh(request)
            return request
    
    @staticmethod
    def get(request_id: str, db: Optional[Session] = None) -> Optional[RouterRequest]:
        """根据 request_id 获取 Router 请求记录"""
        if db is None:
            with Session(engine) as session:
                statement = select(RouterRequest).where(RouterRequest.request_id == request_id)
                return session.exec(statement).first()
        else:
            statement = select(RouterRequest).where(RouterRequest.request_id == request_id)
            return db.exec(statement).first()
    
    @staticmethod
    def list_by_route_type(
        route_type: str,
        limit: int = 100,
        db: Optional[Session] = None,
    ) -> List[RouterRequest]:
        """列出某路由类型的所有请求"""
        if db is None:
            with Session(engine) as session:
                statement = (
                    select(RouterRequest)
                    .where(RouterRequest.route_type == route_type)
                    .order_by(RouterRequest.created_at.desc())
                    .limit(limit)
                )
                return list(session.exec(statement).all())
        else:
            statement = (
                select(RouterRequest)
                .where(RouterRequest.route_type == route_type)
                .order_by(RouterRequest.created_at.desc())
                .limit(limit)
            )
            return list(db.exec(statement).all())
    
    @staticmethod
    def list_all(limit: int = 100, db: Optional[Session] = None) -> List[RouterRequest]:
        """列出所有 Router 请求"""
        if db is None:
            with Session(engine) as session:
                statement = (
                    select(RouterRequest)
                    .order_by(RouterRequest.created_at.desc())
                    .limit(limit)
                )
                return list(session.exec(statement).all())
        else:
            statement = (
                select(RouterRequest)
                .order_by(RouterRequest.created_at.desc())
                .limit(limit)
            )
            return list(db.exec(statement).all())

