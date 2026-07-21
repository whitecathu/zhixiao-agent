"""app/model/task.py
任务 / Agent 步骤 / 断点
"""

from sqlalchemy import (
    BigInteger,
    String,
    Integer,
    SmallInteger,
    TIMESTAMP,
    JSON,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.model.base import Base, BigInt, LongText, PKMixin


class Task(PKMixin, Base):
    __tablename__ = "tasks"
    space_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    goal: Mapped[str] = mapped_column(LongText, nullable=False)
    attachments: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger, default=5, nullable=False)
    template_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    result_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)
    duration_ms: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_message: Mapped[str | None] = mapped_column(LongText, nullable=True)

    __table_args__ = (
        Index("idx_tasks_space_status", "space_id", "status"),
        Index("idx_tasks_user_created", "user_id", "created_at"),
        Index("idx_tasks_template", "template_id"),
    )

    @staticmethod
    def next_status(current: str, target: str) -> bool:
        """任务状态机:: pending -> running -> (succeeded|failed|interrupted)"""
        machine = {
            "pending": {"running"},
            "running": {"succeeded", "failed", "interrupted"},
            "interrupted": {"running"},  # 恢复
            # succeeded/failed: 终态
        }
        return target in machine.get(current, set())


class AgentStep(PKMixin, Base):
    __tablename__ = "agent_steps"
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tasks.id"), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    input: Mapped[str | None] = mapped_column(LongText, nullable=True)
    output: Mapped[str | None] = mapped_column(LongText, nullable=True)
    tools_used: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)
    duration_ms: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(LongText, nullable=True)

    __table_args__ = (
        Index("idx_steps_task", "task_id", "step_index"),
        Index("idx_steps_agent_task", "agent_name", "task_id"),
    )


class ExecutionCheckpoint(Base):
    __tablename__ = "execution_checkpoints"
    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tasks.id"), nullable=False)
    checkpoint_id: Mapped[str] = mapped_column(String(64), nullable=False)
    graph_state: Mapped[str] = mapped_column(LongText, nullable=False)
    created_at: Mapped[str] = mapped_column(
        TIMESTAMP, server_default="CURRENT_TIMESTAMP", nullable=False
    )

    __table_args__ = (Index("idx_cp_task", "task_id", "created_at"),)
