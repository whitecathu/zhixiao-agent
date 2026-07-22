"""Response contracts for space-scoped operational summaries."""

from pydantic import BaseModel, Field


class TaskRunSummary(BaseModel):
    total: int = 0
    active: int = 0
    queued: int = 0
    succeeded: int = 0
    failed: int = 0
    running: int = 0
    awaiting_approval: int = 0
    success_rate: float = 0.0
    first_pass_rate: float = 0.0
    p95_duration_seconds: float = 0.0


class ToolSummary(BaseModel):
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    blocked: int = 0
    success_rate: float = 0.0
    average_duration_seconds: float = 0.0
    invocations: int = 0
    failure_rate: float = 0.0
    p95_duration_ms: float = 0.0


class ApprovalSummary(BaseModel):
    pending: int = 0
    decided: int = 0
    average_wait_seconds: float = 0.0
    p95_wait_seconds: float = 0.0


class ModelUsageSummary(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = Field(
        default=None,
        description="Null until provider cost is persisted by the selected model adapter.",
    )


class QueueSummary(BaseModel):
    depth: int = 0
    oldest_age_seconds: float = 0.0


class SLOSummary(BaseModel):
    task_success_rate: float | None
    first_pass_rate: float | None
    p95_run_duration_ms: float | None
    error_rate: float | None
    cost_usd: float | None
    budget_usd: float


class ModelUsageBreakdown(BaseModel):
    provider: str
    model: str
    tokens: int = 0
    cost_usd: float = 0.0
    calls: int = 0


class RecentFailure(BaseModel):
    run_id: int
    title: str
    error: str
    occurred_at: str


class ObservabilitySummary(BaseModel):
    generated_at: str
    window: str
    window_days: int
    tasks: TaskRunSummary
    tools: ToolSummary
    approvals: ApprovalSummary
    queue_backlog: int = 0
    queue: QueueSummary
    model_usage: ModelUsageSummary
    models: list[ModelUsageBreakdown]
    recent_failures: list[RecentFailure]
    slo: SLOSummary
