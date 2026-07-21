"""init_schema - 智效工坊初始 schema

Revision ID: 0001_init
Revises:
Create Date: 2026-07-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = "0001_init"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("email", sa.String(128), nullable=False, unique=True),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("password_hash", sa.String(128), nullable=False),
        sa.Column("nickname", sa.String(64), nullable=True),
        sa.Column("avatar_url", sa.String(255), nullable=True),
        sa.Column("status", sa.SmallInteger, nullable=False, server_default="1"),
        sa.Column("last_login_at", sa.TIMESTAMP, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("deleted_at", sa.TIMESTAMP, nullable=True),
        mysql_charset="utf8mb4",
    )
    op.create_index("idx_users_email", "users", ["email"])
    op.create_index("idx_users_status", "users", ["status"])

    # refresh_tokens
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("jti", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.TIMESTAMP, nullable=False),
        sa.Column("revoked", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp()),
    )
    op.create_index("idx_rt_user", "refresh_tokens", ["user_id"])
    op.create_index("idx_rt_jti", "refresh_tokens", ["jti"])

    # spaces
    op.create_table(
        "spaces",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("owner_id", sa.BigInteger, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("deleted_at", sa.TIMESTAMP, nullable=True),
    )
    op.create_index("idx_spaces_owner", "spaces", ["owner_id"])

    # space_members
    op.create_table(
        "space_members",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("space_id", sa.BigInteger, sa.ForeignKey("spaces.id"), nullable=False),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp()),
        sa.UniqueConstraint("space_id", "user_id", name="uk_space_user"),
    )

    # tasks
    op.create_table(
        "tasks",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("space_id", sa.BigInteger, nullable=False),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("goal", mysql.MEDIUMTEXT, nullable=False),
        sa.Column("attachments", sa.JSON, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("priority", sa.SmallInteger, nullable=False, server_default="5"),
        sa.Column("template_id", sa.BigInteger, nullable=True),
        sa.Column("result_url", sa.String(255), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP, nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP, nullable=True),
        sa.Column("duration_ms", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(32), nullable=True),
        sa.Column("error_message", mysql.MEDIUMTEXT, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("deleted_at", sa.TIMESTAMP, nullable=True),
    )
    op.create_index("idx_tasks_space_status", "tasks", ["space_id", "status"])
    op.create_index("idx_tasks_user_created", "tasks", ["user_id", "created_at"])

    # agent_steps
    op.create_table(
        "agent_steps",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.BigInteger, sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("agent_name", sa.String(64), nullable=False),
        sa.Column("node_id", sa.String(64), nullable=False),
        sa.Column("step_index", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("input", mysql.MEDIUMTEXT, nullable=True),
        sa.Column("output", mysql.MEDIUMTEXT, nullable=True),
        sa.Column("tools_used", sa.JSON, nullable=True),
        sa.Column("tokens_in", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer, nullable=False, server_default="0"),
        sa.Column("started_at", sa.TIMESTAMP, nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP, nullable=True),
        sa.Column("duration_ms", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("error_message", mysql.MEDIUMTEXT, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("deleted_at", sa.TIMESTAMP, nullable=True),
    )
    op.create_index("idx_steps_task", "agent_steps", ["task_id", "step_index"])
    op.create_index("idx_steps_agent_task", "agent_steps", ["agent_name", "task_id"])

    # execution_checkpoints
    op.create_table(
        "execution_checkpoints",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.BigInteger, sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("checkpoint_id", sa.String(64), nullable=False),
        sa.Column("graph_state", mysql.MEDIUMTEXT, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp()),
    )
    op.create_index("idx_cp_task", "execution_checkpoints", ["task_id", "created_at"])

    # knowledge_items
    op.create_table(
        "knowledge_items",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("space_id", sa.BigInteger, nullable=False),
        sa.Column("source_task_id", sa.BigInteger, nullable=True),
        sa.Column("source_agent_step_id", sa.BigInteger, nullable=True),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", mysql.MEDIUMTEXT, nullable=False),
        sa.Column("summary", sa.String(512), nullable=True),
        sa.Column("tags", sa.JSON, nullable=True),
        sa.Column("category_path", sa.String(255), nullable=True),
        sa.Column("quality_score", sa.DECIMAL(3, 2), nullable=False, server_default="0.50"),
        sa.Column("usage_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.TIMESTAMP, nullable=True),
        sa.Column("vector_ids", sa.JSON, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("deleted_at", sa.TIMESTAMP, nullable=True),
    )
    op.create_index("idx_kn_space_type", "knowledge_items", ["space_id", "type"])
    op.create_index("idx_kn_category", "knowledge_items", ["category_path"])
    op.create_index("idx_kn_quality", "knowledge_items", ["quality_score"])
    op.create_index("idx_kn_source", "knowledge_items", ["source_task_id", "source_agent_step_id"])

    # knowledge_tags / categories / tool_invocations / files / templates / stats
    op.create_table(
        "knowledge_tags",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("space_id", sa.BigInteger, nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.UniqueConstraint("space_id", "name", name="uk_space_name"),
    )
    op.create_table(
        "knowledge_categories",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("space_id", sa.BigInteger, nullable=False),
        sa.Column("parent_id", sa.BigInteger, nullable=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("path", sa.String(255), nullable=True),
    )
    op.create_index("idx_cat_parent", "knowledge_categories", ["parent_id"])
    op.create_index("idx_cat_space_path", "knowledge_categories", ["space_id", "path"])

    op.create_table(
        "tool_invocations",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.BigInteger, nullable=False),
        sa.Column("agent_name", sa.String(64), nullable=False),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column("input", sa.JSON, nullable=True),
        sa.Column("output", sa.JSON, nullable=True),
        sa.Column("success", sa.SmallInteger, nullable=False, server_default="1"),
        sa.Column("duration_ms", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("deleted_at", sa.TIMESTAMP, nullable=True),
    )
    op.create_index("idx_ti_task", "tool_invocations", ["task_id"])
    op.create_index("idx_ti_tool", "tool_invocations", ["tool_name"])

    op.create_table(
        "task_stats_daily",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("space_id", sa.BigInteger, nullable=False),
        sa.Column("stat_date", sa.Date, nullable=False),
        sa.Column("total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("succeeded", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("avg_duration_ms", sa.BigInteger, nullable=False, server_default="0"),
        sa.UniqueConstraint("space_id", "stat_date", name="uk_space_date"),
    )

    op.create_table(
        "agent_metrics",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("agent_name", sa.String(64), nullable=False),
        sa.Column("space_id", sa.BigInteger, nullable=False),
        sa.Column("stat_date", sa.Date, nullable=False),
        sa.Column("invocations", sa.Integer, nullable=False, server_default="0"),
        sa.Column("success_rate", sa.DECIMAL(3, 2), nullable=False, server_default="0.00"),
        sa.Column("avg_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("avg_duration_ms", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("deleted_at", sa.TIMESTAMP, nullable=True),
    )
    op.create_index("idx_am_agent_date", "agent_metrics", ["agent_name", "stat_date"])

    op.create_table(
        "files",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("space_id", sa.BigInteger, nullable=False),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(64), nullable=True),
        sa.Column("size", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("storage_path", sa.String(255), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("deleted_at", sa.TIMESTAMP, nullable=True),
    )
    op.create_index("idx_files_space", "files", ["space_id"])
    op.create_index("idx_files_sha", "files", ["sha256"])

    op.create_table(
        "task_templates",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("space_id", sa.BigInteger, nullable=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("goal", mysql.MEDIUMTEXT, nullable=False),
        sa.Column("workflow_id", sa.BigInteger, nullable=True),
        sa.Column("params", sa.JSON, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("deleted_at", sa.TIMESTAMP, nullable=True),
    )
    op.create_index("idx_tpl_space", "task_templates", ["space_id"])


def downgrade() -> None:
    for tbl in (
        "task_templates", "files", "agent_metrics", "task_stats_daily",
        "tool_invocations", "knowledge_categories", "knowledge_tags",
        "knowledge_items", "execution_checkpoints", "agent_steps", "tasks",
        "space_members", "spaces", "refresh_tokens", "users",
    ):
        op.drop_table(tbl)