"""Add engineering-agent control-plane resources.

Revision ID: 0002_agent_platform
Revises: 0001_init
Create Date: 2026-07-20
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = "0002_agent_platform"
down_revision: str | None = "0001_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("deleted_at", sa.TIMESTAMP(), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "repositories",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("space_id", sa.BigInteger(), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("clone_url", sa.String(1024)),
        sa.Column("root_path", sa.String(1024)),
        sa.Column("default_branch", sa.String(128), nullable=False, server_default="main"),
        sa.Column("status", sa.String(32), nullable=False, server_default="ready"),
        sa.Column("settings", sa.JSON()),
        *timestamps(),
        sa.UniqueConstraint("space_id", "name", name="uk_repository_space_name"),
    )
    op.create_table(
        "model_profiles",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("space_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("base_url", sa.String(1024), nullable=False),
        sa.Column("model_name", sa.String(255), nullable=False),
        sa.Column("api_key_env", sa.String(128)),
        sa.Column("parameters", sa.JSON()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
    )
    op.create_table(
        "workflow_definitions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("space_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.UniqueConstraint("space_id", "name", "version", name="uk_workflow_version"),
    )
    op.create_table(
        "agent_definitions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("space_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("role", sa.String(64), nullable=False),
        sa.Column("system_prompt", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("tool_allowlist", sa.JSON(), nullable=False),
        sa.Column("model_profile_id", sa.BigInteger(), sa.ForeignKey("model_profiles.id")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
    )
    op.create_table(
        "task_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("space_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("repository_id", sa.BigInteger(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("workflow_id", sa.BigInteger(), sa.ForeignKey("workflow_definitions.id")),
        sa.Column("agent_id", sa.BigInteger(), sa.ForeignKey("agent_definitions.id")),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("prompt", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("permission_mode", sa.String(16), nullable=False, server_default="edit"),
        sa.Column("status", sa.String(32), nullable=False, server_default="awaiting_approval"),
        sa.Column("execution_id", sa.String(128)),
        sa.Column("current_step", sa.String(128)),
        sa.Column("diff_text", mysql.MEDIUMTEXT()),
        sa.Column("verification", sa.JSON()),
        sa.Column("error_message", mysql.MEDIUMTEXT()),
        sa.Column("started_at", sa.TIMESTAMP()),
        sa.Column("finished_at", sa.TIMESTAMP()),
        *timestamps(),
    )
    op.create_index("idx_task_runs_space_status", "task_runs", ["space_id", "status"])
    op.create_table(
        "workspaces",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("repository_id", sa.BigInteger(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("task_run_id", sa.BigInteger(), sa.ForeignKey("task_runs.id")),
        sa.Column("root_path", sa.String(1024), nullable=False),
        sa.Column("branch_name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        *timestamps(),
    )
    op.create_table(
        "run_steps",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("task_run_id", sa.BigInteger(), sa.ForeignKey("task_runs.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("input", sa.JSON()),
        sa.Column("output", sa.JSON()),
        sa.Column("error_message", mysql.MEDIUMTEXT()),
        sa.Column("started_at", sa.TIMESTAMP()),
        sa.Column("finished_at", sa.TIMESTAMP()),
        *timestamps(),
        sa.UniqueConstraint("task_run_id", "sequence", name="uk_run_step_sequence"),
    )
    op.create_table(
        "approvals",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("task_run_id", sa.BigInteger(), sa.ForeignKey("task_runs.id"), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(512), nullable=False),
        sa.Column("requested_by", sa.BigInteger(), nullable=False),
        sa.Column("decided_by", sa.BigInteger()),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("comment", sa.String(512)),
        sa.Column("decided_at", sa.TIMESTAMP()),
        *timestamps(),
    )
    op.create_table(
        "artifacts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("task_run_id", sa.BigInteger(), sa.ForeignKey("task_runs.id"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("path", sa.String(1024)),
        sa.Column("mime_type", sa.String(128)),
        sa.Column("size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("checksum", sa.String(128)),
        sa.Column("metadata", sa.JSON()),
        *timestamps(),
    )
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("space_id", sa.BigInteger(), nullable=False),
        sa.Column("model_profile_id", sa.BigInteger(), sa.ForeignKey("model_profiles.id")),
        sa.Column("dataset_name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("metrics", sa.JSON()),
        sa.Column("report_artifact_id", sa.BigInteger(), sa.ForeignKey("artifacts.id")),
        *timestamps(),
    )
    op.create_table(
        "fine_tune_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("space_id", sa.BigInteger(), nullable=False),
        sa.Column("base_model", sa.String(255), nullable=False),
        sa.Column("dataset_artifact_id", sa.BigInteger(), sa.ForeignKey("artifacts.id")),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON()),
        sa.Column("adapter_artifact_id", sa.BigInteger(), sa.ForeignKey("artifacts.id")),
        *timestamps(),
    )
    op.create_table(
        "knowledge_entities",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("space_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("properties", sa.JSON(), nullable=False),
        sa.Column("source_refs", sa.JSON(), nullable=False),
        *timestamps(),
    )
    op.create_table(
        "knowledge_relations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("space_id", sa.BigInteger(), nullable=False),
        sa.Column("source_entity_id", sa.BigInteger(), sa.ForeignKey("knowledge_entities.id"), nullable=False),
        sa.Column("target_entity_id", sa.BigInteger(), sa.ForeignKey("knowledge_entities.id"), nullable=False),
        sa.Column("relation_type", sa.String(64), nullable=False),
        sa.Column("properties", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        *timestamps(),
    )
    op.create_index("idx_relation_source_target", "knowledge_relations",
                    ["source_entity_id", "target_entity_id"])

    op.alter_column("tool_invocations", "task_id", existing_type=sa.BigInteger(), nullable=True)
    op.add_column("tool_invocations", sa.Column("task_run_id", sa.BigInteger(), nullable=True))
    op.add_column("tool_invocations", sa.Column("run_step_id", sa.BigInteger(), nullable=True))
    op.add_column("tool_invocations", sa.Column("status", sa.String(16), nullable=False,
                                                server_default="succeeded"))
    op.add_column("tool_invocations", sa.Column("error_root_cause", sa.String(512)))
    op.add_column("tool_invocations", sa.Column("retry_hint", sa.String(512)))
    op.create_foreign_key("fk_tool_invocation_run", "tool_invocations", "task_runs",
                          ["task_run_id"], ["id"])
    op.create_foreign_key("fk_tool_invocation_step", "tool_invocations", "run_steps",
                          ["run_step_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_tool_invocation_step", "tool_invocations", type_="foreignkey")
    op.drop_constraint("fk_tool_invocation_run", "tool_invocations", type_="foreignkey")
    for column in ("retry_hint", "error_root_cause", "status", "run_step_id", "task_run_id"):
        op.drop_column("tool_invocations", column)
    op.alter_column("tool_invocations", "task_id", existing_type=sa.BigInteger(), nullable=False)
    for table in (
        "knowledge_relations", "knowledge_entities", "fine_tune_jobs", "evaluation_runs",
        "artifacts", "approvals", "run_steps", "workspaces", "task_runs",
        "agent_definitions", "workflow_definitions", "model_profiles", "repositories",
    ):
        op.drop_table(table)
