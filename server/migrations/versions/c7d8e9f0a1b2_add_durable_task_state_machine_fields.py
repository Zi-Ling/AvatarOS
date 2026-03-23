"""add durable task state machine fields

Revision ID: c7d8e9f0a1b2
Revises: b5c2d3e4f6a7
Create Date: 2026-04-01 00:00:00.000000

变更：
  1. task_sessions 新增 Lease 字段、转换元数据、Event Sequence
  2. step_states 新增幂等字段 + (task_session_id, idempotency_key) 唯一约束
  3. checkpoints 新增 Execution Frontier / 幂等 / Effect Ledger / Pending Request 快照字段
  4. 新增 effect_ledger 表（副作用账本）
  5. approval_requests 新增审批类型和超时策略字段
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision: str = 'c7d8e9f0a1b2'
down_revision: Union[str, None] = 'b5c2d3e4f6a7'
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

    # ── 1. task_sessions: Lease 字段 + 转换元数据 + Event Sequence ──
    _task_session_columns = {
        "worker_id":              sa.Column("worker_id", sa.String(), nullable=True),
        "lease_expiry":           sa.Column("lease_expiry", sa.DateTime(timezone=True), nullable=True),
        "last_heartbeat_at":      sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        "heartbeat_interval_s":   sa.Column("heartbeat_interval_s", sa.Integer(), nullable=False, server_default="30"),
        "lease_timeout_s":        sa.Column("lease_timeout_s", sa.Integer(), nullable=False, server_default="90"),
        "last_transition_reason": sa.Column("last_transition_reason", sa.String(), nullable=True),
        "recovery_chain_json":    sa.Column("recovery_chain_json", sa.String(), nullable=True),
        "last_event_sequence":    sa.Column("last_event_sequence", sa.Integer(), nullable=False, server_default="0"),
    }
    with op.batch_alter_table("task_sessions", schema=None) as batch_op:
        for col_name, col_def in _task_session_columns.items():
            if not _column_exists(conn, "task_sessions", col_name):
                batch_op.add_column(col_def)

    # ── 2. step_states: 幂等字段 + 唯一约束 ─────────────────────────
    _step_state_columns = {
        "idempotency_key": sa.Column("idempotency_key", sa.String(), nullable=True),
        "attempt_id":      sa.Column("attempt_id", sa.String(), nullable=True),
        "input_hash":      sa.Column("input_hash", sa.String(), nullable=True),
    }
    with op.batch_alter_table("step_states", schema=None) as batch_op:
        for col_name, col_def in _step_state_columns.items():
            if not _column_exists(conn, "step_states", col_name):
                batch_op.add_column(col_def)
        # 唯一约束 — batch mode 下 SQLite 会重建表
        batch_op.create_unique_constraint(
            "uq_step_state_idempotency",
            ["task_session_id", "idempotency_key"],
        )

    # ── 3. checkpoints: Execution Frontier / 幂等 / Effect Ledger / Pending Request ──
    _checkpoint_columns = {
        "execution_frontier_json":    sa.Column("execution_frontier_json", sa.String(), nullable=True),
        "idempotency_metadata_json":  sa.Column("idempotency_metadata_json", sa.String(), nullable=True),
        "effect_ledger_snapshot_json": sa.Column("effect_ledger_snapshot_json", sa.String(), nullable=True),
        "pending_requests_json":      sa.Column("pending_requests_json", sa.String(), nullable=True),
    }
    with op.batch_alter_table("checkpoints", schema=None) as batch_op:
        for col_name, col_def in _checkpoint_columns.items():
            if not _column_exists(conn, "checkpoints", col_name):
                batch_op.add_column(col_def)

    # ── 4. effect_ledger 新表 ────────────────────────────────────────
    if not _table_exists(conn, "effect_ledger"):
        op.create_table(
            "effect_ledger",
            sa.Column("id",                  sa.String(),  nullable=False),
            sa.Column("task_session_id",      sa.String(),  nullable=False),
            sa.Column("step_id",              sa.String(),  nullable=False),
            sa.Column("effect_type",          sa.String(),  nullable=False),
            sa.Column("status",               sa.String(),  nullable=False, server_default="prepared"),
            sa.Column("external_request_id",  sa.String(),  nullable=True),
            sa.Column("target_path",          sa.String(),  nullable=True),
            sa.Column("content_hash",         sa.String(),  nullable=True),
            sa.Column("remote_receipt",        sa.String(),  nullable=True),
            sa.Column("metadata_json",        sa.String(),  nullable=True),
            sa.Column("compensation_details", sa.String(),  nullable=True),
            sa.Column("created_at",           sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at",           sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_effect_ledger_task_session_id", "effect_ledger", ["task_session_id"], unique=False)
        op.create_index("ix_effect_ledger_step_id",         "effect_ledger", ["step_id"],         unique=False)
        op.create_index("ix_effect_ledger_status",          "effect_ledger", ["status"],          unique=False)

    # ── 5. approval_requests: 审批类型 + 超时策略 ────────────────────
    _approval_columns = {
        "approval_type":     sa.Column("approval_type", sa.String(), nullable=False, server_default="quick"),
        "parent_request_id": sa.Column("parent_request_id", sa.String(), nullable=True),
        "timeout_action":    sa.Column("timeout_action", sa.String(), nullable=False, server_default="mark_timeout"),
    }
    with op.batch_alter_table("approval_requests", schema=None) as batch_op:
        for col_name, col_def in _approval_columns.items():
            if not _column_exists(conn, "approval_requests", col_name):
                batch_op.add_column(col_def)
        if not _column_exists(conn, "approval_requests", "parent_request_id"):
            batch_op.create_index("ix_approval_requests_parent_request_id", ["parent_request_id"], unique=False)


def downgrade() -> None:
    conn = op.get_bind()

    # ── 5. approval_requests ─────────────────────────────────────────
    with op.batch_alter_table("approval_requests", schema=None) as batch_op:
        for col_name in ("timeout_action", "parent_request_id", "approval_type"):
            if _column_exists(conn, "approval_requests", col_name):
                batch_op.drop_column(col_name)

    # ── 4. effect_ledger ─────────────────────────────────────────────
    if _table_exists(conn, "effect_ledger"):
        op.drop_index("ix_effect_ledger_status",          table_name="effect_ledger")
        op.drop_index("ix_effect_ledger_step_id",         table_name="effect_ledger")
        op.drop_index("ix_effect_ledger_task_session_id", table_name="effect_ledger")
        op.drop_table("effect_ledger")

    # ── 3. checkpoints ───────────────────────────────────────────────
    with op.batch_alter_table("checkpoints", schema=None) as batch_op:
        for col_name in ("pending_requests_json", "effect_ledger_snapshot_json",
                         "idempotency_metadata_json", "execution_frontier_json"):
            if _column_exists(conn, "checkpoints", col_name):
                batch_op.drop_column(col_name)

    # ── 2. step_states ───────────────────────────────────────────────
    with op.batch_alter_table("step_states", schema=None) as batch_op:
        batch_op.drop_constraint("uq_step_state_idempotency", type_="unique")
        for col_name in ("input_hash", "attempt_id", "idempotency_key"):
            if _column_exists(conn, "step_states", col_name):
                batch_op.drop_column(col_name)

    # ── 1. task_sessions ─────────────────────────────────────────────
    with op.batch_alter_table("task_sessions", schema=None) as batch_op:
        for col_name in ("last_event_sequence", "recovery_chain_json", "last_transition_reason",
                         "lease_timeout_s", "heartbeat_interval_s", "last_heartbeat_at",
                         "lease_expiry", "worker_id"):
            if _column_exists(conn, "task_sessions", col_name):
                batch_op.drop_column(col_name)
