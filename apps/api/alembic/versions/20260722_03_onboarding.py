"""Add resumable onboarding state and space defaults.

Revision ID: 0003_onboarding
Revises: 0002_agent_platform
Create Date: 2026-07-22
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0003_onboarding"
down_revision: str | None = "0002_agent_platform"
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
    op.create_table(
        "onboarding_states",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("space_id", sa.BigInteger(), sa.ForeignKey("spaces.id"), nullable=False),
        sa.Column("completed_steps", sa.JSON(), nullable=False),
        sa.Column("skipped", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("replay_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("finished_at", sa.TIMESTAMP(), nullable=True),
        *timestamps(),
        sa.UniqueConstraint("user_id", "space_id", name="uk_onboarding_user_space"),
    )
    op.create_table(
        "space_onboarding_configs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "space_id",
            sa.BigInteger(),
            sa.ForeignKey("spaces.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("recommended_template", sa.String(128), nullable=True),
        sa.Column(
            "default_workflow_id",
            sa.BigInteger(),
            sa.ForeignKey("workflow_definitions.id"),
            nullable=True,
        ),
        *timestamps(),
    )


def downgrade() -> None:
    op.drop_table("space_onboarding_configs")
    op.drop_table("onboarding_states")
