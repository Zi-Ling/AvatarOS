"""add conversation_id to execution_sessions and create artifact_records table

Revision ID: a3f1c2d4e5b6
Revises: 1410a2a6e291
Create Date: 2026-03-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision: str = 'a3f1c2d4e5b6'
down_revision: Union[str, None] = '1410a2a6e291'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(text(f"PRAGMA table_info({table})"))
    return any(row[1] == column for row in result)


def _table_exists(conn, table: str) -> bool:
    result = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
        {"t": table},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()

    # ── execution_sessions: 加 conversation_id（幂等）────────────────
    if not _column_exists(conn, 'execution_sessions', 'conversation_id'):
        with op.batch_alter_table('execution_sessions', schema=None) as batch_op:
            batch_op.add_column(sa.Column('conversation_id', sa.String(), nullable=True))
            batch_op.create_index(
                'ix_execution_sessions_conversation_id',
                ['conversation_id'],
                unique=False,
            )

    # ── artifact_records 表（幂等）───────────────────────────────────
    if not _table_exists(conn, 'artifact_records'):
        op.create_table(
            'artifact_records',
            sa.Column('id',            sa.String(),  nullable=False),
            sa.Column('artifact_id',   sa.String(),  nullable=False),
            sa.Column('session_id',    sa.String(),  nullable=False),
            sa.Column('step_id',       sa.String(),  nullable=True),
            sa.Column('filename',      sa.String(),  nullable=False),
            sa.Column('storage_uri',   sa.String(),  nullable=False),
            sa.Column('size',          sa.Integer(), nullable=False, server_default='0'),
            sa.Column('checksum',      sa.String(),  nullable=True),
            sa.Column('mime_type',     sa.String(),  nullable=True),
            sa.Column('artifact_type', sa.String(),  nullable=False, server_default='file'),
            sa.Column('created_at',    sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_artifact_records_id',          'artifact_records', ['id'],          unique=False)
        op.create_index('ix_artifact_records_artifact_id', 'artifact_records', ['artifact_id'], unique=False)
        op.create_index('ix_artifact_records_session_id',  'artifact_records', ['session_id'],  unique=False)
        op.create_index('ix_artifact_records_step_id',     'artifact_records', ['step_id'],     unique=False)


def downgrade() -> None:
    conn = op.get_bind()

    if _table_exists(conn, 'artifact_records'):
        op.drop_index('ix_artifact_records_step_id',     table_name='artifact_records')
        op.drop_index('ix_artifact_records_session_id',  table_name='artifact_records')
        op.drop_index('ix_artifact_records_artifact_id', table_name='artifact_records')
        op.drop_index('ix_artifact_records_id',          table_name='artifact_records')
        op.drop_table('artifact_records')

    if _column_exists(conn, 'execution_sessions', 'conversation_id'):
        with op.batch_alter_table('execution_sessions', schema=None) as batch_op:
            batch_op.drop_index('ix_execution_sessions_conversation_id')
            batch_op.drop_column('conversation_id')
