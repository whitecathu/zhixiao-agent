from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class PermissionMode(StrEnum):
    READ_ONLY = "read_only"
    EDIT = "edit"
    EXECUTE = "execute"
    FULL = "full"


class ToolStatus(StrEnum):
    SUCCESS = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    # Compatibility aliases for the original prototype API.
    ERROR = "failed"
    WARNING = "blocked"
    APPROVAL_REQUIRED = "blocked"


class RunStatus(StrEnum):
    PENDING = "pending"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class VerificationOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class TerminationReason(StrEnum):
    COMPLETED = "completed"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVAL_DENIED = "approval_denied"
    VERIFICATION_FAILED = "verification_failed"
    VERIFICATION_BLOCKED = "verification_blocked"
    BUDGET_EXHAUSTED = "budget_exhausted"
    MODEL_ERROR = "model_error"
    TOOL_LOOP = "tool_loop"
    INTERRUPTED = "interrupted"
    RUNTIME_ERROR = "runtime_error"


class TaskType(StrEnum):
    BUGFIX = "bugfix"
    FEATURE = "feature"
    REFACTOR = "refactor"
    TEST = "test"
    REVIEW = "review"
    DOCUMENTATION = "documentation"
    OPERATIONS = "operations"
    EXPLORE = "explore"


class Artifact(BaseModel):
    kind: str
    path: str
    description: str = ""
    sha256: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    mime_type: str | None = None
    base_sha: str | None = None
    truncated: bool = False


class ToolResult(BaseModel):
    status: ToolStatus
    summary: str
    data: Any = None
    next_actions: list[str] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    root_cause: str | None = None
    retry: str | None = None
    stop_condition: str | None = None

    @classmethod
    def ok(
        cls, summary: str, data: Any = None, *, artifacts: list[Artifact] | None = None
    ) -> ToolResult:
        return cls(
            status=ToolStatus.SUCCESS,
            summary=summary,
            data=data,
            artifacts=artifacts or [],
        )

    @classmethod
    def error(
        cls,
        summary: str,
        *,
        root_cause: str,
        retry: str | None = None,
        stop_condition: str | None = None,
    ) -> ToolResult:
        return cls(
            status=ToolStatus.ERROR,
            summary=summary,
            root_cause=root_cause,
            retry=retry,
            stop_condition=stop_condition,
        )

    @classmethod
    def blocked(
        cls,
        summary: str,
        *,
        root_cause: str,
        retry: str | None = None,
        stop_condition: str | None = None,
    ) -> ToolResult:
        return cls(
            status=ToolStatus.BLOCKED,
            summary=summary,
            root_cause=root_cause,
            retry=retry,
            stop_condition=stop_condition,
        )


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ModelTurn(BaseModel):
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    cost_usd: float = 0.0


class TodoItem(BaseModel):
    id: str
    content: str
    status: Literal["pending", "in_progress", "completed", "cancelled"] = "pending"


class AgentEvent(BaseModel):
    schema_version: str = "1.1"
    sequence: int
    run_id: str
    event: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class VerificationStage(BaseModel):
    name: str
    command: str | None = None
    outcome: VerificationOutcome
    exit_code: int | None = None
    summary: str = ""
    artifacts: list[Artifact] = Field(default_factory=list)


class VerificationResult(BaseModel):
    outcome: VerificationOutcome = VerificationOutcome.SKIPPED
    reason: str = ""
    waived: bool = False
    waiver_reason: str | None = None
    stages: list[VerificationStage] = Field(default_factory=list)


class RunBudget(BaseModel):
    max_model_turns: int = Field(default=30, ge=1)
    max_tool_calls: int = Field(default=50, ge=1)
    max_tokens: int = Field(default=200_000, ge=1)
    max_cost_usd: float | None = Field(default=None, gt=0)
    max_duration_seconds: int = Field(default=1_800, ge=1)


class RunUsage(BaseModel):
    model_turns: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)
    elapsed_seconds: float = Field(default=0.0, ge=0)


class RunResult(BaseModel):
    schema_version: str = "1.1"
    run_id: str
    status: RunStatus
    summary: str
    task_type: TaskType
    plan: list[str] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    test_command: str | None = None
    test_exit_code: int | None = None
    diff: str = ""
    events: list[AgentEvent] = Field(default_factory=list)
    error: str | None = None
    verification: VerificationResult = Field(default_factory=VerificationResult)
    termination_reason: TerminationReason | None = None
    usage: RunUsage = Field(default_factory=RunUsage)
    budgets: RunBudget = Field(default_factory=RunBudget)
    next_actions: list[str] = Field(default_factory=list)
