"""add AOS workbench fields: interrupt_type, modifications, pause_context_json

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-03-24 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Feature 1: Interrupt Type System
    op.add_column("approval_requests", sa.Column("interrupt_type", sa.String(), server_default="approval_required", nullable=False))
    # Feature 3: Multi-Action Decision (modifications JSON)
    op.add_column("approval_requests", sa.Column("modifications", sa.JSON(), nullable=True))
    # Feature 2: Continuity Card Real Data
    op.add_column("task_sessions", sa.Column("pause_context_json", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("task_sessions", "pause_context_json")
    op.drop_column("approval_requests", "modifications")
    op.drop_column("approval_requests", "interrupt_type")
