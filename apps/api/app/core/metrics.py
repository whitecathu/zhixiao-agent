"""Low-cardinality Prometheus metrics for the API and agent runtime.

Metric labels are deliberately constrained to fixed allowlists. Callers must never
pass prompts, repository paths, task identifiers, usernames, or model names.
"""

from __future__ import annotations

import time
from typing import Final

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

METRICS_REGISTRY = CollectorRegistry(auto_describe=True)

API_REQUESTS = Counter(
    "zhixiao_api_requests_total",
    "API requests grouped by route template and status class.",
    ("method", "route", "status_class"),
    registry=METRICS_REGISTRY,
)
API_LATENCY = Histogram(
    "zhixiao_api_request_duration_seconds",
    "API request duration grouped by route template.",
    ("method", "route"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
    registry=METRICS_REGISTRY,
)
TASK_RUNS_ACTIVE = Gauge(
    "zhixiao_task_runs_active",
    "Current task runs by bounded lifecycle state.",
    ("status",),
    registry=METRICS_REGISTRY,
)
TASK_RUNS_COMPLETED = Counter(
    "zhixiao_task_runs_completed_total",
    "Completed task runs by terminal result.",
    ("status",),
    registry=METRICS_REGISTRY,
)
TASK_RUN_DURATION = Histogram(
    "zhixiao_task_run_duration_seconds",
    "Completed task run duration.",
    ("status",),
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600, 7200),
    registry=METRICS_REGISTRY,
)
TOOL_INVOCATIONS = Counter(
    "zhixiao_tool_invocations_total",
    "Tool invocations by fixed tool category and result.",
    ("category", "status"),
    registry=METRICS_REGISTRY,
)
TOOL_DURATION = Histogram(
    "zhixiao_tool_invocation_duration_seconds",
    "Tool invocation duration by fixed tool category.",
    ("category",),
    buckets=(0.01, 0.05, 0.1, 0.5, 1, 2.5, 5, 15, 30, 60, 120, 300),
    registry=METRICS_REGISTRY,
)
APPROVAL_WAIT = Histogram(
    "zhixiao_approval_wait_seconds",
    "Human approval wait time by bounded outcome.",
    ("outcome",),
    buckets=(1, 5, 15, 30, 60, 300, 900, 1800, 3600, 14400, 86400),
    registry=METRICS_REGISTRY,
)
QUEUE_DEPTH = Gauge(
    "zhixiao_queue_depth",
    "Current pending work by fixed queue.",
    ("queue",),
    registry=METRICS_REGISTRY,
)
MODEL_TOKENS = Counter(
    "zhixiao_model_tokens_total",
    "Model tokens by known provider and direction.",
    ("provider", "direction"),
    registry=METRICS_REGISTRY,
)
MODEL_COST = Counter(
    "zhixiao_model_cost_usd_total",
    "Estimated model cost in USD by known provider.",
    ("provider",),
    registry=METRICS_REGISTRY,
)

_METHODS: Final = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"})
_TASK_STATES: Final = frozenset(
    {"awaiting_approval", "queued", "running", "interrupted", "succeeded", "failed", "cancelled"}
)
_TOOL_RESULTS: Final = frozenset({"succeeded", "failed", "blocked"})
_APPROVAL_OUTCOMES: Final = frozenset({"approved", "rejected", "expired", "cancelled"})
_QUEUES: Final = frozenset({"task_runs", "background_jobs", "fine_tunes", "evaluations"})
_PROVIDERS: Final = frozenset({"openai", "xai", "deepseek", "qwen", "vllm", "local"})


def _bounded(value: str, allowed: frozenset[str]) -> str:
    normalized = value.strip().lower()
    return normalized if normalized in allowed else "other"


def _tool_category(tool_name: str) -> str:
    name = tool_name.strip().lower()
    prefixes = (
        (("read", "write", "edit", "file", "list_dir", "search"), "filesystem"),
        (("git",), "git"),
        (("test", "pytest", "lint", "typecheck"), "verification"),
        (("terminal", "shell", "command", "background"), "terminal"),
        (("web", "browser", "http"), "web"),
        (("knowledge", "vector", "graph"), "knowledge"),
        (("mcp",), "mcp"),
        (("todo",), "todo"),
        (("subagent", "sub_agent"), "subagent"),
    )
    for candidates, category in prefixes:
        if name.startswith(candidates):
            return category
    return "other"


def record_task_run(status: str, duration_seconds: float | None = None) -> None:
    state = _bounded(status, _TASK_STATES)
    if state in {"succeeded", "failed", "cancelled"}:
        TASK_RUNS_COMPLETED.labels(status=state).inc()
        if duration_seconds is not None:
            TASK_RUN_DURATION.labels(status=state).observe(max(duration_seconds, 0.0))


def set_active_task_runs(status: str, count: int) -> None:
    state = _bounded(status, _TASK_STATES)
    TASK_RUNS_ACTIVE.labels(status=state).set(max(count, 0))


def record_tool_invocation(tool_name: str, status: str, duration_seconds: float) -> None:
    category = _tool_category(tool_name)
    result = _bounded(status, _TOOL_RESULTS)
    TOOL_INVOCATIONS.labels(category=category, status=result).inc()
    TOOL_DURATION.labels(category=category).observe(max(duration_seconds, 0.0))


def record_approval(outcome: str, wait_seconds: float) -> None:
    APPROVAL_WAIT.labels(outcome=_bounded(outcome, _APPROVAL_OUTCOMES)).observe(
        max(wait_seconds, 0.0)
    )


def set_queue_depth(queue: str, depth: int) -> None:
    QUEUE_DEPTH.labels(queue=_bounded(queue, _QUEUES)).set(max(depth, 0))


def record_model_usage(
    provider: str, *, prompt_tokens: int, completion_tokens: int, cost_usd: float
) -> None:
    bounded_provider = _bounded(provider, _PROVIDERS)
    MODEL_TOKENS.labels(provider=bounded_provider, direction="input").inc(max(prompt_tokens, 0))
    MODEL_TOKENS.labels(provider=bounded_provider, direction="output").inc(
        max(completion_tokens, 0)
    )
    MODEL_COST.labels(provider=bounded_provider).inc(max(cost_usd, 0.0))


class PrometheusMiddleware:
    """Small ASGI middleware that records route templates rather than raw URLs."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or scope.get("path") == "/metrics":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status_code = 500

        async def send_with_status(message: Message) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", 500))
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        finally:
            request = Request(scope)
            route = request.scope.get("route")
            route_template = getattr(route, "path", "__unmatched__")
            method = str(scope.get("method", "OTHER")).upper()
            if method not in _METHODS:
                method = "OTHER"
            status_class = f"{status_code // 100}xx"
            API_REQUESTS.labels(
                method=method, route=route_template, status_class=status_class
            ).inc()
            API_LATENCY.labels(method=method, route=route_template).observe(
                time.perf_counter() - started
            )
