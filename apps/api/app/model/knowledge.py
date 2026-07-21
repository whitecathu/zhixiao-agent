"""app/model/knowledge.py
知识 / 标签 / 分类 / 工具调用日志 / 统计 / 文件 / 模板
"""

from decimal import Decimal
from sqlalchemy import (
    BigInteger,
    String,
    Integer,
    SmallInteger,
    TIMESTAMP,
    Date,
    JSON,
    ForeignKey,
    DECIMAL,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.model.base import Base, BigInt, LongText, PKMixin


class KnowledgeItem(PKMixin, Base):
    __tablename__ = "knowledge_items"
    space_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_task_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_agent_step_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(LongText, nullable=False)
    summary: Mapped[str | None] = mapped_column(String(512), nullable=True)
    tags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    category_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quality_score: Mapped[Decimal] = mapped_column(
        DECIMAL(3, 2), default=Decimal("0.50"), nullable=False
    )
    usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_used_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)
    vector_ids: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default="active", nullable=False
    )  # active|vector_pending|deprecated

    __table_args__ = (
        Index("idx_kn_space_type", "space_id", "type"),
        Index("idx_kn_category", "category_path"),
        Index("idx_kn_quality", "quality_score"),
        Index("idx_kn_source", "source_task_id", "source_agent_step_id"),
    )


class KnowledgeTag(Base):
    __tablename__ = "knowledge_tags"
    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    space_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (UniqueConstraint("space_id", "name", name="uk_space_name"),)


class KnowledgeCategory(Base):
    __tablename__ = "knowledge_categories"
    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    space_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    path: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        Index("idx_cat_parent", "parent_id"),
        Index("idx_cat_space_path", "space_id", "path"),
    )


class ToolInvocation(PKMixin, Base):
    __tablename__ = "tool_invocations"
    task_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    task_run_id: Mapped[int | None] = mapped_column(
        BigInt, ForeignKey("task_runs.id"), nullable=True
    )
    run_step_id: Mapped[int | None] = mapped_column(
        BigInt, ForeignKey("run_steps.id"), nullable=True
    )
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    input: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    success: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="succeeded", nullable=False)
    error_root_cause: Mapped[str | None] = mapped_column(String(512), nullable=True)
    retry_hint: Mapped[str | None] = mapped_column(String(512), nullable=True)
    duration_ms: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    __table_args__ = (
        Index("idx_ti_task", "task_id"),
        Index("idx_ti_tool", "tool_name"),
    )


class TaskStatsDaily(Base):
    __tablename__ = "task_stats_daily"
    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    space_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    stat_date: Mapped[str] = mapped_column(Date, nullable=False)
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    succeeded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_duration_ms: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    __table_args__ = (UniqueConstraint("space_id", "stat_date", name="uk_space_date"),)


class AgentMetric(PKMixin, Base):
    __tablename__ = "agent_metrics"
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    space_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    stat_date: Mapped[str] = mapped_column(Date, nullable=False)
    invocations: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_rate: Mapped[Decimal] = mapped_column(
        DECIMAL(3, 2), default=Decimal("0.00"), nullable=False
    )
    avg_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_duration_ms: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    __table_args__ = (Index("idx_am_agent_date", "agent_name", "stat_date"),)


class FileAsset(PKMixin, Base):
    __tablename__ = "files"
    space_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)  # upload / agent_output
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("idx_files_space", "space_id"),
        Index("idx_files_sha", "sha256"),
    )


class TaskTemplate(PKMixin, Base):
    __tablename__ = "task_templates"
    space_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    goal: Mapped[str] = mapped_column(LongText, nullable=False)
    workflow_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (Index("idx_tpl_space", "space_id"),)
