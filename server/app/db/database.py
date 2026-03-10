# app/db/database.py
"""
数据库初始化和会话管理（使用 SQLModel）
唯一数据库：~/.avatar/avatar.db
"""
from sqlmodel import create_engine, Session, SQLModel
from typing import Generator
import logging

from app.core.config import AVATAR_DB_PATH

SQLALCHEMY_DATABASE_URL = f"sqlite:///{AVATAR_DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)


def init_db():
    """
    初始化数据库（创建所有表）。
    必须先导入所有模型，SQLModel 才能注册表。
    """
    from app.db.task.task import Task, Run, Step                          # noqa: F401
    from app.db.task.schedule import Schedule                              # noqa: F401
    from app.db.logging import LLMCall, RouterRequest                     # noqa: F401
    from app.db.workflow import WorkflowTemplateDB, WorkflowRunDB, WorkflowStageRunDB  # noqa: F401
    from app.db.system import ApprovalRequest, Grant, KVState, AuditLog, ExecutionSession, PlannerInvocation  # noqa: F401
    from app.avatar.runtime.graph.storage.step_trace_store import SessionTraceRecord, StepTraceRecord  # noqa: F401
    from app.db.file_artifact import FileArtifact                         # noqa: F401

    SQLModel.metadata.create_all(engine)
    logging.getLogger(__name__).info(f"数据库初始化完成: {AVATAR_DB_PATH}")


def get_db() -> Generator[Session, None, None]:
    """获取数据库会话（用于 FastAPI 依赖注入）"""
    with Session(engine) as session:
        yield session
