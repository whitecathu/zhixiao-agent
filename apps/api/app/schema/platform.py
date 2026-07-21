"""Public request and response contracts for the engineering-agent platform."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class ORMOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True, protected_namespaces=())
    id: int
    created_at: datetime
    updated_at: datetime


class RepositoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    clone_url: str | None = Field(
        default=None,
        max_length=1024,
        validation_alias=AliasChoices("clone_url", "remote_url"),
    )
    root_path: str | None = Field(
        default=None,
        max_length=1024,
        validation_alias=AliasChoices("root_path", "path"),
    )
    default_branch: str = Field(default="main", min_length=1, max_length=128)
    settings: dict[str, Any] | None = None

    @model_validator(mode="after")
    def require_source(self) -> RepositoryCreate:
        if not self.clone_url and not self.root_path:
            raise ValueError("clone_url or root_path is required")
        return self


class RepositoryOut(ORMOut):
    space_id: int
    owner_id: int
    name: str
    clone_url: str | None
    root_path: str | None
    default_branch: str
    status: str
    settings: dict[str, Any] | None


class WorkspaceCreate(BaseModel):
    task_run_id: int | None = None
    root_path: str = Field(min_length=1, max_length=1024)
    branch_name: str = Field(min_length=1, max_length=255)


class WorkspaceOut(ORMOut):
    repository_id: int
    task_run_id: int | None
    root_path: str
    branch_name: str
    status: str


class TaskRunCreate(BaseModel):
    repository_id: int
    title: str = Field(min_length=2, max_length=255)
    prompt: str = Field(min_length=10)
    workflow_id: int | None = None
    agent_id: int | None = None
    permission_mode: Literal["read_only", "edit", "execute", "full"] = "edit"


class TaskRunOut(ORMOut):
    space_id: int
    user_id: int
    repository_id: int
    workflow_id: int | None
    agent_id: int | None
    title: str
    prompt: str
    permission_mode: str
    status: str
    execution_id: str | None
    current_step: str | None
    verification: dict[str, Any] | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None


class RunStepCreate(BaseModel):
    sequence: int = Field(ge=0)
    role: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    status: Literal["pending", "running", "succeeded", "failed", "blocked"] = "pending"
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None


class RunStepOut(ORMOut):
    task_run_id: int
    sequence: int
    role: str
    name: str
    status: str
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None


class ToolResult(BaseModel):
    status: Literal["succeeded", "failed", "blocked"]
    summary: str
    data: Any = None
    next_actions: list[str] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    error_root_cause: str | None = None
    retry_hint: str | None = None
    stop_reason: str | None = None


class ToolInvocationCreate(BaseModel):
    run_step_id: int | None = None
    agent_name: str = Field(min_length=1, max_length=64)
    tool_name: str = Field(min_length=1, max_length=64)
    input: dict[str, Any] | None = None
    result: ToolResult
    duration_ms: int = Field(default=0, ge=0)


class ToolInvocationOut(ORMOut):
    task_run_id: int | None
    run_step_id: int | None
    agent_name: str
    tool_name: str
    input: dict[str, Any] | None
    result: ToolResult = Field(validation_alias="output")
    status: str
    duration_ms: int


class ApprovalDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: str | None = Field(default=None, max_length=512)


class ApprovalOut(ORMOut):
    task_run_id: int
    operation: str
    reason: str
    requested_by: int
    decided_by: int | None
    status: str
    comment: str | None
    decided_at: datetime | None


class ArtifactCreate(BaseModel):
    kind: Literal["diff", "test_report", "log", "dataset", "adapter", "report", "other"]
    name: str = Field(min_length=1, max_length=255)
    path: str | None = Field(default=None, max_length=1024)
    mime_type: str | None = Field(default=None, max_length=128)
    size: int = Field(default=0, ge=0)
    checksum: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] | None = None


class ArtifactOut(ORMOut):
    task_run_id: int
    kind: str
    name: str
    path: str | None
    mime_type: str | None
    size: int
    checksum: str | None
    metadata: dict[str, Any] | None = Field(validation_alias="metadata_")


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    version: int = Field(default=1, ge=1)
    definition: dict[str, Any]
    enabled: bool = True

    @model_validator(mode="after")
    def validate_graph(self) -> WorkflowCreate:
        nodes = self.definition.get("nodes")
        edges = self.definition.get("edges")
        if not isinstance(nodes, list) or not nodes:
            raise ValueError("definition.nodes must be a non-empty list")
        if not isinstance(edges, list):
            raise ValueError("definition.edges must be a list")
        ids = [node.get("id") for node in nodes if isinstance(node, dict)]
        if len(ids) != len(nodes) or len(set(ids)) != len(ids) or any(not item for item in ids):
            raise ValueError("workflow node ids must be present and unique")
        return self


class WorkflowOut(ORMOut):
    space_id: int
    name: str
    version: int
    definition: dict[str, Any]
    enabled: bool


class WorkflowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    definition: dict[str, Any] | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def validate_graph(self) -> WorkflowUpdate:
        if self.definition is not None:
            WorkflowCreate(
                name=self.name or "validation",
                definition=self.definition,
                enabled=self.enabled if self.enabled is not None else True,
            )
        if not self.model_fields_set:
            raise ValueError("at least one workflow field is required")
        return self


class AgentCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    name: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=64)
    system_prompt: str = Field(min_length=1)
    tool_allowlist: list[str] = Field(default_factory=list)
    model_profile_id: int | None = None
    enabled: bool = True


class AgentOut(ORMOut):
    space_id: int
    name: str
    role: str
    system_prompt: str
    tool_allowlist: list[str]
    model_profile_id: int | None
    enabled: bool


class AgentUpdate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    name: str | None = Field(default=None, min_length=1, max_length=128)
    role: str | None = Field(default=None, min_length=1, max_length=64)
    system_prompt: str | None = Field(default=None, min_length=1)
    tool_allowlist: list[str] | None = None
    model_profile_id: int | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def require_changes(self) -> AgentUpdate:
        if not self.model_fields_set:
            raise ValueError("at least one agent field is required")
        return self


class ModelProfileCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    name: str = Field(min_length=1, max_length=128)
    provider: Literal["xai", "openai", "deepseek", "qwen", "vllm"]
    base_url: str = Field(min_length=1, max_length=1024)
    model_name: str = Field(min_length=1, max_length=255)
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    parameters: dict[str, Any] | None = None
    enabled: bool = True


class ModelProfileOut(ORMOut):
    space_id: int
    name: str
    provider: str
    base_url: str
    model_name: str
    api_key_env: str | None
    parameters: dict[str, Any] | None
    enabled: bool


class ModelProfileUpdate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    name: str | None = Field(default=None, min_length=1, max_length=128)
    provider: Literal["xai", "openai", "deepseek", "qwen", "vllm"] | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=1024)
    model_name: str | None = Field(default=None, min_length=1, max_length=255)
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    parameters: dict[str, Any] | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def require_changes(self) -> ModelProfileUpdate:
        if not self.model_fields_set:
            raise ValueError("at least one model field is required")
        return self


class EvaluationCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    dataset_name: str = Field(min_length=1, max_length=255)
    model_profile_id: int | None = None


class EvaluationOut(ORMOut):
    space_id: int
    model_profile_id: int | None
    dataset_name: str
    status: str
    metrics: dict[str, Any] | None
    report_artifact_id: int | None


class FineTuneCreate(BaseModel):
    base_model: str = Field(min_length=1, max_length=255)
    dataset_artifact_id: int | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class FineTuneOut(ORMOut):
    space_id: int
    base_model: str
    dataset_artifact_id: int | None
    status: str
    config: dict[str, Any]
    metrics: dict[str, Any] | None
    adapter_artifact_id: int | None


class KnowledgeEntityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    entity_type: str = Field(min_length=1, max_length=64)
    properties: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)


class KnowledgeEntityOut(ORMOut):
    space_id: int
    name: str
    entity_type: str
    properties: dict[str, Any]
    source_refs: list[dict[str, Any]]


class KnowledgeRelationCreate(BaseModel):
    source_entity_id: int
    target_entity_id: int
    relation_type: str = Field(min_length=1, max_length=64)
    properties: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class KnowledgeRelationOut(ORMOut):
    space_id: int
    source_entity_id: int
    target_entity_id: int
    relation_type: str
    properties: dict[str, Any]
    evidence: list[dict[str, Any]]


class DiffOut(BaseModel):
    task_run_id: int
    unified_diff: str
    content: str
    verified: bool


class WebApprovalDecision(ApprovalDecision):
    approval_id: int


class WorkerRunResult(BaseModel):
    run_id: str
    status: Literal["succeeded", "failed", "interrupted", "awaiting_approval"]
    summary: str = ""
    task_type: str = "explore"
    plan: list[str] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    test_command: str | None = None
    test_exit_code: int | None = None
    diff: str = ""
    events: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class ToolDescriptor(BaseModel):
    name: str
    permission: Literal["read_only", "edit", "execute", "full"]
    description: str
    result_contract: dict[str, Any]
