"""Public request and response contracts for the engineering-agent platform."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

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
        if self.clone_url:
            parsed = urlsplit(self.clone_url)
            if parsed.scheme != "https" or not parsed.hostname:
                raise ValueError("clone_url must be an HTTPS repository URL")
            if parsed.username or parsed.password:
                raise ValueError("clone_url must not contain embedded credentials")
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
    workflow_version: int | None
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


class ApprovalRequest(BaseModel):
    operation: Literal[
        "destructive_command",
        "git_publish",
        "mcp",
        "sub_agent",
        "network_tools",
    ]
    reason: str | None = Field(default=None, min_length=3, max_length=512)


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


WORKFLOW_ROLES = frozenset(
    {"planner", "explorer", "implementer", "tester", "reviewer", "knowledge"}
)
WORKFLOW_TOOLS = frozenset(
    {
        "list_directory",
        "read_file",
        "grep",
        "exact_edit",
        "write_file",
        "terminal",
        "run_tests",
        "git_status",
        "git_diff",
        "web_search",
        "web_fetch",
        "todo",
        "background_command",
        "sub_agent",
        "knowledge_search",
        "mcp",
        "open_pull_request",
    }
)
AGENT_ROLES = frozenset(
    {
        "planner",
        "explorer",
        "implementer",
        "tester",
        "reviewer",
        "knowledge",
        "metagpt",
        "team",
        "metagpt_team",
    }
)


class WorkflowPosition(BaseModel):
    x: float = Field(ge=-100_000, le=100_000)
    y: float = Field(ge=-100_000, le=100_000)


class WorkflowNode(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    role: Literal["planner", "explorer", "implementer", "tester", "reviewer", "knowledge"] = Field(
        validation_alias=AliasChoices("role", "type")
    )
    label: str | None = Field(default=None, min_length=1, max_length=128)
    position: WorkflowPosition | None = None
    tool_allowlist: list[str] = Field(default_factory=list, max_length=32)
    retry_limit: int = Field(
        default=0,
        ge=0,
        le=5,
        validation_alias=AliasChoices("retry_limit", "retries"),
    )
    approval_required: bool = False

    @model_validator(mode="after")
    def validate_tools(self) -> WorkflowNode:
        unknown = sorted(set(self.tool_allowlist) - WORKFLOW_TOOLS)
        if unknown:
            raise ValueError(f"unknown workflow tools: {', '.join(unknown)}")
        if len(set(self.tool_allowlist)) != len(self.tool_allowlist):
            raise ValueError("workflow node tool_allowlist must be unique")
        return self


class WorkflowEdge(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    target: str = Field(min_length=1, max_length=64)
    condition: Literal["always", "success", "failure"] = "always"


class WorkflowDSL(BaseModel):
    schema_version: Literal[1] = 1
    entrypoint: str | None = Field(default=None, min_length=1, max_length=64)
    nodes: list[WorkflowNode] = Field(min_length=1, max_length=64)
    edges: list[WorkflowEdge] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def validate_graph(self) -> WorkflowDSL:
        node_ids = [node.id for node in self.nodes]
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("workflow node ids must be unique")
        known = set(node_ids)
        entrypoint = self.entrypoint or node_ids[0]
        if entrypoint not in known:
            raise ValueError("workflow entrypoint must reference a node")
        self.entrypoint = entrypoint

        seen_edges: set[tuple[str, str, str]] = set()
        outgoing: dict[str, list[WorkflowEdge]] = {node_id: [] for node_id in node_ids}
        incoming: dict[str, int] = {node_id: 0 for node_id in node_ids}
        for edge in self.edges:
            if edge.source not in known or edge.target not in known:
                raise ValueError("workflow edges must reference existing nodes")
            if edge.source == edge.target:
                raise ValueError("workflow self-cycles are not allowed")
            key = (edge.source, edge.target, edge.condition)
            if key in seen_edges:
                raise ValueError("workflow edges must be unique")
            seen_edges.add(key)
            outgoing[edge.source].append(edge)
            incoming[edge.target] += 1

        for edges in outgoing.values():
            conditions = [edge.condition for edge in edges]
            if len(set(conditions)) != len(conditions):
                raise ValueError("a node can have at most one edge per condition")
            if "always" in conditions and len(conditions) > 1:
                raise ValueError("an always edge cannot be combined with conditional edges")

        pending = [node_id for node_id, degree in incoming.items() if degree == 0]
        visited: list[str] = []
        while pending:
            current = pending.pop()
            visited.append(current)
            for edge in outgoing[current]:
                incoming[edge.target] -= 1
                if incoming[edge.target] == 0:
                    pending.append(edge.target)
        if len(visited) != len(node_ids):
            raise ValueError("workflow cycles are not allowed")

        reachable = {entrypoint}
        frontier = [entrypoint]
        while frontier:
            current = frontier.pop()
            for edge in outgoing[current]:
                if edge.target not in reachable:
                    reachable.add(edge.target)
                    frontier.append(edge.target)
        if reachable != known:
            raise ValueError("all workflow nodes must be reachable from the entrypoint")
        return self


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    version: int = Field(default=1, ge=1)
    definition: WorkflowDSL
    enabled: bool = True


class WorkflowOut(ORMOut):
    space_id: int
    name: str
    version: int
    definition: dict[str, Any]
    enabled: bool
    status: str
    published_at: datetime | None


class WorkflowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    definition: WorkflowDSL | None = None
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


class KnowledgeGraphExplore(BaseModel):
    query: str | None = Field(default=None, min_length=1, max_length=255)
    entity_types: list[str] = Field(default_factory=list, max_length=16)
    entity_id: int | None = Field(default=None, ge=1)
    depth: int = Field(default=1, ge=0, le=3)
    limit: int = Field(default=50, ge=1, le=100)


class KnowledgeEvidenceLink(BaseModel):
    kind: Literal["entity", "relation"]
    relation_id: int | None = None
    entity_id: int | None = None
    source_entity_id: int | None = None
    target_entity_id: int | None = None
    relation_type: str | None = None
    evidence: list[dict[str, Any]]


class KnowledgeGraphExploreOut(BaseModel):
    entities: list[KnowledgeEntityOut]
    relations: list[KnowledgeRelationOut]
    evidence_chain: list[KnowledgeEvidenceLink]
    evidence_sufficient: bool
    evidence_status: Literal["sufficient", "no_matches", "no_source_evidence"]
    truncated: bool
    retrieval_mode: Literal["relational_graph"] = "relational_graph"


class AgentCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    name: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=64)
    system_prompt: str = Field(min_length=1)
    tool_allowlist: list[str] = Field(default_factory=list, max_length=32)
    model_profile_id: int | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def validate_agent(self) -> AgentCreate:
        _validate_agent_role_and_tools(self.role, self.tool_allowlist)
        return self


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
    tool_allowlist: list[str] | None = Field(default=None, max_length=32)
    model_profile_id: int | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def require_changes(self) -> AgentUpdate:
        if not self.model_fields_set:
            raise ValueError("at least one agent field is required")
        _validate_agent_role_and_tools(self.role, self.tool_allowlist)
        return self


def _validate_agent_role_and_tools(role: str | None, tools: list[str] | None) -> None:
    if role is not None and role not in AGENT_ROLES:
        raise ValueError(f"unknown agent role: {role}")
    if tools is None:
        return
    unknown = sorted(set(tools) - WORKFLOW_TOOLS)
    if unknown:
        raise ValueError(f"unknown agent tools: {', '.join(unknown)}")
    if len(set(tools)) != len(tools):
        raise ValueError("agent tool_allowlist must be unique")


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
