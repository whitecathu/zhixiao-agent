"""Add resumable task metadata and secret-free MCP definitions.

Revision ID: 0005_agent_cli_control
Revises: 0004_workflow_publish
Create Date: 2026-08-13
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_agent_cli_control"
down_revision: str | None = "0004_workflow_publish"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.TIMESTAMP(), nullable=True),
    ]


def upgrade() -> None:
    op.add_column(
        "task_runs",
        sa.Column("parent_run_id", sa.BigInteger(), nullable=True),
    )
    op.add_column("task_runs", sa.Column("session_name", sa.String(128), nullable=True))
    op.add_column(
        "task_runs", sa.Column("termination_reason", sa.String(64), nullable=True)
    )
    op.add_column("task_runs", sa.Column("budget_snapshot", sa.JSON(), nullable=True))
    op.add_column("task_runs", sa.Column("usage_snapshot", sa.JSON(), nullable=True))
    op.add_column(
        "task_runs", sa.Column("allow_unverified", sa.String(512), nullable=True)
    )
    op.add_column(
        "task_runs", sa.Column("verification_commands", sa.JSON(), nullable=True)
    )
    op.create_foreign_key(
        "fk_task_runs_parent",
        "task_runs",
        "task_runs",
        ["parent_run_id"],
        ["id"],
    )
    op.create_index("idx_task_runs_parent", "task_runs", ["parent_run_id"])

    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("space_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("transport", sa.String(16), nullable=False),
        sa.Column("command", sa.String(512), nullable=True),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("url", sa.String(1024), nullable=True),
        sa.Column("env_refs", sa.JSON(), nullable=False),
        sa.Column("credential_env", sa.String(128), nullable=True),
        sa.Column("tool_allowlist", sa.JSON(), nullable=False),
        sa.Column(
            "startup_timeout_seconds", sa.Integer(), nullable=False, server_default="10"
        ),
        sa.Column(
            "call_timeout_seconds", sa.Integer(), nullable=False, server_default="60"
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.UniqueConstraint("space_id", "name", name="uk_mcp_server_space_name"),
    )


def downgrade() -> None:
    op.drop_table("mcp_servers")
    op.drop_index("idx_task_runs_parent", table_name="task_runs")
    op.drop_constraint("fk_task_runs_parent", "task_runs", type_="foreignkey")
    for column in (
        "verification_commands",
        "allow_unverified",
        "usage_snapshot",
        "budget_snapshot",
        "termination_reason",
        "session_name",
        "parent_run_id",
    ):
        op.drop_column("task_runs", column)
