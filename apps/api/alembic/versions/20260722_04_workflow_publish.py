"""Bind task runs to published workflow versions.

Revision ID: 0004_workflow_publish
Revises: 0003_onboarding
Create Date: 2026-07-22
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004_workflow_publish"
down_revision: str | None = "0003_onboarding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_definitions",
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
    )
    op.add_column(
        "workflow_definitions",
        sa.Column("published_at", sa.TIMESTAMP(), nullable=True),
    )
    op.create_index(
        "idx_workflow_space_status",
        "workflow_definitions",
        ["space_id", "status"],
    )
    op.add_column("task_runs", sa.Column("workflow_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("task_runs", "workflow_version")
    op.drop_index("idx_workflow_space_status", table_name="workflow_definitions")
    op.drop_column("workflow_definitions", "published_at")
    op.drop_column("workflow_definitions", "status")
