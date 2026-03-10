"""add event_traces table and artifact consumed_by_step_ids

Revision ID: b5c2d3e4f6a7
Revises: a3f1c2d4e5b6
Create Date: 2026-03-11 00:00:00.000000

变更：
  1. 新增 event_traces 表（第三层细粒度 trace）
  2. artifact_records 加 consumed_by_step_ids_json 列（artifact 血缘）
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision: str = 'b5c2d3e4f6a7'
down_revision: Union[str, None] = 'a3f1c2d4e5b6'
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

    # ── event_traces 表（幂等）───────────────────────────────────────
    if not _table_exists(conn, 'event_traces'):
        op.create_table(
            'event_traces',
            sa.Column('id',           sa.Integer(),  nullable=False, autoincrement=True),
            sa.Column('session_id',   sa.String(),   nullable=False),
            sa.Column('step_id',      sa.String(),   nullable=True),
            sa.Column('event_type',   sa.String(),   nullable=False),
            sa.Column('container_id', sa.String(),   nullable=True),
            sa.Column('artifact_id',  sa.String(),   nullable=True),
            sa.Column('payload_json', sa.Text(),     nullable=True),
            sa.Column('created_at',   sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_event_traces_session_id',   'event_traces', ['session_id'],   unique=False)
        op.create_index('ix_event_traces_step_id',      'event_traces', ['step_id'],      unique=False)
        op.create_index('ix_event_traces_event_type',   'event_traces', ['event_type'],   unique=False)
        op.create_index('ix_event_traces_container_id', 'event_traces', ['container_id'], unique=False)
        op.create_index('ix_event_traces_artifact_id',  'event_traces', ['artifact_id'],  unique=False)

    # ── artifact_records: 加 consumed_by_step_ids_json（幂等）────────
    if not _column_exists(conn, 'artifact_records', 'consumed_by_step_ids_json'):
        with op.batch_alter_table('artifact_records', schema=None) as batch_op:
            batch_op.add_column(
                sa.Column('consumed_by_step_ids_json', sa.Text(), nullable=True)
            )


def downgrade() -> None:
    conn = op.get_bind()

    if _table_exists(conn, 'event_traces'):
        op.drop_index('ix_event_traces_artifact_id',  table_name='event_traces')
        op.drop_index('ix_event_traces_container_id', table_name='event_traces')
        op.drop_index('ix_event_traces_event_type',   table_name='event_traces')
        op.drop_index('ix_event_traces_step_id',      table_name='event_traces')
        op.drop_index('ix_event_traces_session_id',   table_name='event_traces')
        op.drop_table('event_traces')

    if _column_exists(conn, 'artifact_records', 'consumed_by_step_ids_json'):
        with op.batch_alter_table('artifact_records', schema=None) as batch_op:
            batch_op.drop_column('consumed_by_step_ids_json')
