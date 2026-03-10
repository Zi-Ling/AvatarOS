from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# 导入所有模型，确保 SQLModel metadata 注册完整
from app.db.task.task import Task, Run, Step                          # noqa: F401
from app.db.task.schedule import Schedule                              # noqa: F401
from app.db.logging.llm import LLMCall                                # noqa: F401
from app.db.logging.router import RouterRequest                       # noqa: F401
from app.db.workflow import WorkflowTemplateDB, WorkflowRunDB, WorkflowStageRunDB  # noqa: F401
from app.db.system import ApprovalRequest, Grant, KVState, AuditLog, ExecutionSession, PlannerInvocation  # noqa: F401
from app.db.file_artifact import FileArtifact                         # noqa: F401
from app.db.artifact_record import ArtifactRecord                     # noqa: F401
from app.avatar.runtime.graph.storage.step_trace_store import SessionTraceRecord, StepTraceRecord  # noqa: F401
from sqlmodel import SQLModel

target_metadata = SQLModel.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite 需要 batch mode 支持 ALTER TABLE
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from app.db.database import engine as app_engine
    from app.core.config import ensure_avatar_home
    ensure_avatar_home()

    with app_engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite 需要 batch mode 支持 ALTER TABLE
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
