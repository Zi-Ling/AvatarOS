"""add version lineage fields and preview thin abstraction

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-03-24 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "e9f0a1b2c3d4"
down_revision: Union[str, None] = "d8e9f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Version Lineage: parent_version_id + version_source on artifact_versions
    op.add_column("artifact_versions", sa.Column("parent_version_id", sa.String(), nullable=True))
    op.add_column("artifact_versions", sa.Column("version_source", sa.String(), server_default="initial", nullable=False))
    op.create_index("ix_artifact_versions_parent_version_id", "artifact_versions", ["parent_version_id"])

    # Preview Thin Abstraction: preview_url + preview_state on artifact_records
    op.add_column("artifact_records", sa.Column("preview_url", sa.String(), nullable=True))
    op.add_column("artifact_records", sa.Column("preview_state", sa.String(), server_default="none", nullable=False))


def downgrade() -> None:
    op.drop_column("artifact_records", "preview_state")
    op.drop_column("artifact_records", "preview_url")
    op.drop_index("ix_artifact_versions_parent_version_id", table_name="artifact_versions")
    op.drop_column("artifact_versions", "version_source")
    op.drop_column("artifact_versions", "parent_version_id")
