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
    sequence: int
    run_id: str
    event: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RunResult(BaseModel):
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
