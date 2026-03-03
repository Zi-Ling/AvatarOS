# app/db/database.py
"""
数据库初始化和会话管理（使用 SQLModel）
"""
from sqlmodel import create_engine, Session, SQLModel
from typing import Generator
import logging

from app.core.config import config

# 数据库路径
DB_PATH = config.avatar_workspace / "avatar.db"
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

# 创建引擎
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite 需要
    echo=False,  # 生产环境关闭 SQL 日志
)


def init_db():
    """
    初始化数据库（创建所有表）
    
    注意：必须先导入所有模型，SQLModel 才能创建表
    """
    # 导入所有模型以确保它们被注册
    from app.db.task.task import Task, Run, Step  # noqa: F401
    from app.db.task.schedule import Schedule       # noqa: F401
    from app.db.logging import LLMCall, RouterRequest  # noqa: F401
    from app.db.workflow import WorkflowTemplateDB, WorkflowRunDB, WorkflowStageRunDB  # noqa: F401
    
    SQLModel.metadata.create_all(engine)
    logging.getLogger(__name__).info(f"数据库初始化完成: {DB_PATH}")


def get_db() -> Generator[Session, None, None]:
    """
    获取数据库会话（用于 FastAPI 依赖注入）
    """
    with Session(engine) as session:
        yield session

