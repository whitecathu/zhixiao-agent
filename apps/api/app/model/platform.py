"""Core persistence models for the software-engineering agent platform."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.model.base import Base, BigInt, LongText, PKMixin, SAJSON


class Repository(PKMixin, Base):
    __tablename__ = "repositories"
    space_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    owner_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    clone_url: Mapped[str | None] = mapped_column(String(1024))
    root_path: Mapped[str | None] = mapped_column(String(1024))
    default_branch: Mapped[str] = mapped_column(String(128), default="main", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ready", nullable=False)
    settings: Mapped[dict | None] = mapped_column(SAJSON)

    __table_args__ = (UniqueConstraint("space_id", "name", name="uk_repository_space_name"),)


class Workspace(PKMixin, Base):
    __tablename__ = "workspaces"
    repository_id: Mapped[int] = mapped_column(
        BigInt, ForeignKey("repositories.id"), nullable=False
    )
    task_run_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("task_runs.id"))
    root_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    branch_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class TaskRun(PKMixin, Base):
    __tablename__ = "task_runs"
    space_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    repository_id: Mapped[int] = mapped_column(
        BigInt, ForeignKey("repositories.id"), nullable=False
    )
    workflow_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("workflow_definitions.id"))
    agent_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("agent_definitions.id"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt: Mapped[str] = mapped_column(LongText, nullable=False)
    permission_mode: Mapped[str] = mapped_column(String(16), default="edit", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="awaiting_approval", nullable=False)
    execution_id: Mapped[str | None] = mapped_column(String(128))
    current_step: Mapped[str | None] = mapped_column(String(128))
    diff_text: Mapped[str | None] = mapped_column(LongText)
    verification: Mapped[dict | None] = mapped_column(SAJSON)
    error_message: Mapped[str | None] = mapped_column(LongText)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]

    __table_args__ = (Index("idx_task_runs_space_status", "space_id", "status"),)

    @staticmethod
    def can_transition(current: str, target: str) -> bool:
        transitions = {
            "awaiting_approval": {"queued", "running", "interrupted", "cancelled"},
            "queued": {"running", "interrupted", "failed"},
            "running": {"interrupted", "succeeded", "failed", "awaiting_approval"},
            "interrupted": {"running", "cancelled"},
        }
        return target in transitions.get(current, set())


class RunStep(PKMixin, Base):
    __tablename__ = "run_steps"
    task_run_id: Mapped[int] = mapped_column(BigInt, ForeignKey("task_runs.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    input: Mapped[dict | None] = mapped_column(SAJSON)
    output: Mapped[dict | None] = mapped_column(SAJSON)
    error_message: Mapped[str | None] = mapped_column(LongText)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]

    __table_args__ = (UniqueConstraint("task_run_id", "sequence", name="uk_run_step_sequence"),)


class Approval(PKMixin, Base):
    __tablename__ = "approvals"
    task_run_id: Mapped[int] = mapped_column(BigInt, ForeignKey("task_runs.id"), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    requested_by: Mapped[int] = mapped_column(BigInt, nullable=False)
    decided_by: Mapped[int | None] = mapped_column(BigInt)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    comment: Mapped[str | None] = mapped_column(String(512))
    decided_at: Mapped[datetime | None]


class Artifact(PKMixin, Base):
    __tablename__ = "artifacts"
    task_run_id: Mapped[int] = mapped_column(BigInt, ForeignKey("task_runs.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str | None] = mapped_column(String(1024))
    mime_type: Mapped[str | None] = mapped_column(String(128))
    size: Mapped[int] = mapped_column(BigInt, default=0, nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(128))
    metadata_: Mapped[dict | None] = mapped_column("metadata", SAJSON)


class WorkflowDefinition(PKMixin, Base):
    __tablename__ = "workflow_definitions"
    space_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    definition: Mapped[dict] = mapped_column(SAJSON, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (UniqueConstraint("space_id", "name", "version", name="uk_workflow_version"),)


class AgentDefinition(PKMixin, Base):
    __tablename__ = "agent_definitions"
    space_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    system_prompt: Mapped[str] = mapped_column(LongText, nullable=False)
    tool_allowlist: Mapped[list] = mapped_column(SAJSON, default=list, nullable=False)
    model_profile_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("model_profiles.id"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ModelProfile(PKMixin, Base):
    __tablename__ = "model_profiles"
    space_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key_env: Mapped[str | None] = mapped_column(String(128))
    parameters: Mapped[dict | None] = mapped_column(SAJSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class EvaluationRun(PKMixin, Base):
    __tablename__ = "evaluation_runs"
    space_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    model_profile_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("model_profiles.id"))
    dataset_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    metrics: Mapped[dict | None] = mapped_column(SAJSON)
    report_artifact_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("artifacts.id"))


class FineTuneJob(PKMixin, Base):
    __tablename__ = "fine_tune_jobs"
    space_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    base_model: Mapped[str] = mapped_column(String(255), nullable=False)
    dataset_artifact_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("artifacts.id"))
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    config: Mapped[dict] = mapped_column(SAJSON, default=dict, nullable=False)
    metrics: Mapped[dict | None] = mapped_column(SAJSON)
    adapter_artifact_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("artifacts.id"))


class KnowledgeEntity(PKMixin, Base):
    __tablename__ = "knowledge_entities"
    space_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    properties: Mapped[dict] = mapped_column(SAJSON, default=dict, nullable=False)
    source_refs: Mapped[list] = mapped_column(SAJSON, default=list, nullable=False)


class KnowledgeRelation(PKMixin, Base):
    __tablename__ = "knowledge_relations"
    space_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    source_entity_id: Mapped[int] = mapped_column(
        BigInt, ForeignKey("knowledge_entities.id"), nullable=False
    )
    target_entity_id: Mapped[int] = mapped_column(
        BigInt, ForeignKey("knowledge_entities.id"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    properties: Mapped[dict] = mapped_column(SAJSON, default=dict, nullable=False)
    evidence: Mapped[list] = mapped_column(SAJSON, default=list, nullable=False)

    __table_args__ = (Index("idx_relation_source_target", "source_entity_id", "target_entity_id"),)


__all__ = [
    "Repository",
    "Workspace",
    "TaskRun",
    "RunStep",
    "Approval",
    "Artifact",
    "WorkflowDefinition",
    "AgentDefinition",
    "ModelProfile",
    "EvaluationRun",
    "FineTuneJob",
    "KnowledgeEntity",
    "KnowledgeRelation",
]
