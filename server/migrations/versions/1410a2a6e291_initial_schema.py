"""initial_schema

Revision ID: 1410a2a6e291
Revises: 
Create Date: 2026-03-10 22:28:25.797211

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1410a2a6e291'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── execution_sessions ────────────────────────────────────────────
    op.create_table(
        'execution_sessions',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('run_id', sa.Text(), nullable=True),
        sa.Column('task_id', sa.Text(), nullable=True),
        sa.Column('request_id', sa.Text(), nullable=True),
        sa.Column('trace_id', sa.Text(), nullable=True),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('result_status', sa.Text(), nullable=True),
        sa.Column('goal', sa.Text(), nullable=True),
        sa.Column('workspace_path', sa.Text(), nullable=True),
        sa.Column('runtime_config_snapshot', sa.JSON(), nullable=True),
        sa.Column('policy_snapshot', sa.JSON(), nullable=True),
        sa.Column('total_nodes', sa.Integer(), nullable=False),
        sa.Column('completed_nodes', sa.Integer(), nullable=False),
        sa.Column('failed_nodes', sa.Integer(), nullable=False),
        sa.Column('planner_invocations', sa.Integer(), nullable=False),
        sa.Column('planner_tokens', sa.Integer(), nullable=False),
        sa.Column('planner_cost_usd', sa.Float(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('planned_at', sa.DateTime(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('archived_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_execution_sessions_id', 'execution_sessions', ['id'])
    op.create_index('ix_execution_sessions_run_id', 'execution_sessions', ['run_id'])
    op.create_index('ix_execution_sessions_task_id', 'execution_sessions', ['task_id'])
    op.create_index('ix_execution_sessions_request_id', 'execution_sessions', ['request_id'])
    op.create_index('ix_execution_sessions_trace_id', 'execution_sessions', ['trace_id'])
    op.create_index('ix_execution_sessions_status', 'execution_sessions', ['status'])

    # ── planner_invocations ───────────────────────────────────────────
    op.create_table(
        'planner_invocations',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('session_id', sa.Text(), nullable=False),
        sa.Column('invocation_index', sa.Integer(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('tokens_used', sa.Integer(), nullable=False),
        sa.Column('cost_usd', sa.Float(), nullable=False),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('input_summary', sa.Text(), nullable=True),
        sa.Column('output_summary', sa.Text(), nullable=True),
        sa.Column('full_input_json', sa.Text(), nullable=True),
        sa.Column('full_output_json', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_planner_invocations_session_id', 'planner_invocations', ['session_id'])
    op.create_index('ix_planner_invocations_invocation_index', 'planner_invocations', ['invocation_index'])

    # ── session_traces ────────────────────────────────────────────────
    op.create_table(
        'session_traces',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Text(), nullable=False),
        sa.Column('task_id', sa.Text(), nullable=True),
        sa.Column('event_type', sa.Text(), nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_session_traces_session_id', 'session_traces', ['session_id'])
    op.create_index('ix_session_traces_event_type', 'session_traces', ['event_type'])

    # ── step_traces ───────────────────────────────────────────────────
    op.create_table(
        'step_traces',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Text(), nullable=False),
        sa.Column('graph_id', sa.Text(), nullable=True),
        sa.Column('step_id', sa.Text(), nullable=False),
        sa.Column('step_type', sa.Text(), nullable=True),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.Column('execution_time_s', sa.Float(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False),
        sa.Column('error_code', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('container_id', sa.Text(), nullable=True),
        sa.Column('sandbox_backend', sa.Text(), nullable=True),
        sa.Column('workspace_path', sa.Text(), nullable=True),
        sa.Column('stdout_ref', sa.Text(), nullable=True),
        sa.Column('stderr_ref', sa.Text(), nullable=True),
        sa.Column('artifact_ids_json', sa.Text(), nullable=True),
        sa.Column('input_summary', sa.Text(), nullable=True),
        sa.Column('output_summary', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_step_traces_session_id', 'step_traces', ['session_id'])
    op.create_index('ix_step_traces_graph_id', 'step_traces', ['graph_id'])
    op.create_index('ix_step_traces_step_id', 'step_traces', ['step_id'])

    # ── approval_requests ─────────────────────────────────────────────
    op.create_table(
        'approval_requests',
        sa.Column('request_id', sa.Text(), nullable=False),
        sa.Column('task_id', sa.Text(), nullable=True),
        sa.Column('step_id', sa.Text(), nullable=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('operation', sa.Text(), nullable=False),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('user_comment', sa.Text(), nullable=True),
        sa.Column('responded_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('request_id'),
    )
    op.create_index('ix_approval_requests_task_id', 'approval_requests', ['task_id'])
    op.create_index('ix_approval_requests_status', 'approval_requests', ['status'])

    # ── grants ────────────────────────────────────────────────────────
    op.create_table(
        'grants',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('approval_request_id', sa.Text(), nullable=True),
        sa.Column('path_pattern', sa.Text(), nullable=False),
        sa.Column('operations', sa.JSON(), nullable=False),
        sa.Column('scope', sa.Text(), nullable=False),
        sa.Column('scope_id', sa.Text(), nullable=True),
        sa.Column('granted_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('revoked', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_grants_approval_request_id', 'grants', ['approval_request_id'])
    op.create_index('ix_grants_path_pattern', 'grants', ['path_pattern'])
    op.create_index('ix_grants_scope_id', 'grants', ['scope_id'])

    # ── kv_state ──────────────────────────────────────────────────────
    op.create_table(
        'kv_state',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('scope', sa.Text(), nullable=False),
        sa.Column('scope_id', sa.Text(), nullable=False),
        sa.Column('key', sa.Text(), nullable=False),
        sa.Column('value', sa.JSON(), nullable=True),
        sa.Column('ttl_seconds', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_kv_state_scope', 'kv_state', ['scope'])
    op.create_index('ix_kv_state_scope_id', 'kv_state', ['scope_id'])
    op.create_index('ix_kv_state_key', 'kv_state', ['key'])

    # ── audit_logs ────────────────────────────────────────────────────
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('event_type', sa.Text(), nullable=False),
        sa.Column('actor', sa.Text(), nullable=True),
        sa.Column('resource', sa.Text(), nullable=True),
        sa.Column('operation', sa.Text(), nullable=True),
        sa.Column('outcome', sa.Text(), nullable=False),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_logs_id', 'audit_logs', ['id'])
    op.create_index('ix_audit_logs_event_type', 'audit_logs', ['event_type'])


def downgrade() -> None:
    op.drop_table('audit_logs')
    op.drop_table('kv_state')
    op.drop_table('grants')
    op.drop_table('approval_requests')
    op.drop_table('step_traces')
    op.drop_table('session_traces')
    op.drop_table('planner_invocations')
    op.drop_table('execution_sessions')
