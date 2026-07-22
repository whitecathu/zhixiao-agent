"""Space-scoped operational aggregation without sensitive dimensions."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.model.knowledge import ToolInvocation
from app.model.platform import Approval, TaskRun
from app.model.task import AgentStep, Task
from app.schema.observability import (
    ApprovalSummary,
    ModelUsageBreakdown,
    ModelUsageSummary,
    ObservabilitySummary,
    QueueSummary,
    RecentFailure,
    SLOSummary,
    TaskRunSummary,
    ToolSummary,
)


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * quantile) - 1)
    return ordered[index]


def _duration_seconds(started_at: datetime | None, finished_at: datetime | None) -> float | None:
    if started_at is None or finished_at is None:
        return None
    started = started_at.replace(tzinfo=UTC) if started_at.tzinfo is None else started_at
    finished = finished_at.replace(tzinfo=UTC) if finished_at.tzinfo is None else finished_at
    return max((finished - started).total_seconds(), 0.0)


class ObservabilityService:
    def __init__(self, session: AsyncSession, config: Settings = settings) -> None:
        self.session = session
        self.config = config

    async def summary(self, space_id: int, window: str = "24h") -> ObservabilitySummary:
        window_delta = {
            "1h": timedelta(hours=1),
            "24h": timedelta(hours=24),
            "7d": timedelta(days=7),
            "30d": timedelta(days=30),
        }[window]
        generated_at = datetime.now(UTC)
        since = generated_at - window_delta
        runs = list(
            (
                await self.session.scalars(
                    select(TaskRun).where(
                        TaskRun.space_id == space_id,
                        TaskRun.created_at >= since,
                        TaskRun.deleted_at.is_(None),
                    )
                )
            ).all()
        )
        run_ids = [run.id for run in runs]

        terminal = [run for run in runs if run.status in {"succeeded", "failed"}]
        succeeded = sum(run.status == "succeeded" for run in terminal)
        failed = sum(run.status == "failed" for run in terminal)
        durations = [
            duration
            for run in terminal
            if (duration := _duration_seconds(run.started_at, run.finished_at)) is not None
        ]
        verified = [run.verification or {} for run in terminal if run.verification]
        first_passed = sum(
            bool(item.get("passed"))
            and int(item.get("attempts", item.get("test_attempts", 1)) or 1) <= 1
            for item in verified
        )
        tasks = TaskRunSummary(
            total=len(runs),
            active=sum(
                run.status in {"running", "awaiting_approval", "interrupted"} for run in runs
            ),
            queued=sum(run.status == "queued" for run in runs),
            succeeded=succeeded,
            failed=failed,
            running=sum(run.status == "running" for run in runs),
            awaiting_approval=sum(run.status == "awaiting_approval" for run in runs),
            success_rate=round(succeeded / len(terminal), 4) if terminal else 0.0,
            first_pass_rate=round(first_passed / len(verified), 4) if verified else 0.0,
            p95_duration_seconds=round(_percentile(durations, 0.95), 3),
        )

        invocations: list[ToolInvocation] = []
        approvals: list[Approval] = []
        if run_ids:
            invocations = list(
                (
                    await self.session.scalars(
                        select(ToolInvocation).where(
                            ToolInvocation.task_run_id.in_(run_ids),
                            ToolInvocation.deleted_at.is_(None),
                        )
                    )
                ).all()
            )
            approvals = list(
                (
                    await self.session.scalars(
                        select(Approval).where(
                            Approval.task_run_id.in_(run_ids), Approval.deleted_at.is_(None)
                        )
                    )
                ).all()
            )

        tool_succeeded = sum(item.status == "succeeded" for item in invocations)
        tool_failed = sum(item.status == "failed" for item in invocations)
        tool_blocked = sum(item.status == "blocked" for item in invocations)
        tool_durations_ms = [float(max(item.duration_ms, 0)) for item in invocations]
        tools = ToolSummary(
            total=len(invocations),
            succeeded=tool_succeeded,
            failed=tool_failed,
            blocked=tool_blocked,
            success_rate=round(tool_succeeded / len(invocations), 4) if invocations else 0.0,
            average_duration_seconds=round(
                sum(max(item.duration_ms, 0) for item in invocations) / len(invocations) / 1000,
                3,
            )
            if invocations
            else 0.0,
            invocations=len(invocations),
            failure_rate=round(tool_failed / len(invocations), 4) if invocations else 0.0,
            p95_duration_ms=round(_percentile(tool_durations_ms, 0.95), 3),
        )

        decided_waits = [
            duration
            for item in approvals
            if (duration := _duration_seconds(item.created_at, item.decided_at)) is not None
        ]
        approval_summary = ApprovalSummary(
            pending=sum(item.status == "pending" for item in approvals),
            decided=len(decided_waits),
            average_wait_seconds=round(sum(decided_waits) / len(decided_waits), 3)
            if decided_waits
            else 0.0,
            p95_wait_seconds=round(_percentile(decided_waits, 0.95), 3),
        )

        prompt_tokens = 0
        completion_tokens = 0
        cost_usd = 0.0
        has_cost = False
        model_totals: dict[tuple[str, str], dict[str, float | int]] = {}
        for run in runs:
            verification = run.verification or {}
            usage = verification.get("model_usage")
            if not isinstance(usage, dict):
                continue
            prompt_tokens += max(int(usage.get("prompt_tokens", 0) or 0), 0)
            completion_tokens += max(int(usage.get("completion_tokens", 0) or 0), 0)
            cost_usd += max(float(usage.get("cost_usd", 0.0) or 0.0), 0.0)
            has_cost = True
            for item in usage.get("models", []):
                if not isinstance(item, dict):
                    continue
                provider = str(item.get("provider", "other"))[:32]
                model = str(item.get("model", "unknown"))[:255]
                total = model_totals.setdefault(
                    (provider, model), {"tokens": 0, "cost_usd": 0.0, "calls": 0}
                )
                total["tokens"] += max(int(item.get("tokens", 0) or 0), 0)
                total["cost_usd"] += max(float(item.get("cost_usd", 0.0) or 0.0), 0.0)
                total["calls"] += max(int(item.get("calls", 0) or 0), 0)
        legacy_task_ids = list(
            (
                await self.session.scalars(
                    select(Task.id).where(Task.space_id == space_id, Task.created_at >= since)
                )
            ).all()
        )
        if legacy_task_ids and prompt_tokens == 0 and completion_tokens == 0:
            steps = list(
                (
                    await self.session.scalars(
                        select(AgentStep).where(AgentStep.task_id.in_(legacy_task_ids))
                    )
                ).all()
            )
            prompt_tokens = sum(max(step.tokens_in, 0) for step in steps)
            completion_tokens = sum(max(step.tokens_out, 0) for step in steps)
        model_usage = ModelUsageSummary(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=round(cost_usd, 6) if has_cost else None,
        )

        slo = SLOSummary(
            task_success_rate=tasks.success_rate if terminal else None,
            first_pass_rate=tasks.first_pass_rate if verified else None,
            p95_run_duration_ms=(tasks.p95_duration_seconds * 1000 if durations else None),
            error_rate=round(failed / len(terminal), 4) if terminal else None,
            cost_usd=model_usage.cost_usd,
            budget_usd=self.config.SLO_MONTHLY_COST_BUDGET_USD,
        )
        queued_runs = [run for run in runs if run.status == "queued"]
        oldest_queue_age = max(
            (
                max((generated_at - run.created_at.replace(tzinfo=UTC)).total_seconds(), 0.0)
                for run in queued_runs
            ),
            default=0.0,
        )
        recent_failures = sorted(
            (run for run in runs if run.status == "failed"),
            key=lambda run: run.finished_at or run.updated_at,
            reverse=True,
        )[:10]
        return ObservabilitySummary(
            generated_at=generated_at.isoformat(),
            window=window,
            window_days=max(1, math.ceil(window_delta.total_seconds() / 86400)),
            tasks=tasks,
            tools=tools,
            approvals=approval_summary,
            queue_backlog=tasks.queued,
            queue=QueueSummary(
                depth=tasks.queued,
                oldest_age_seconds=round(oldest_queue_age, 3),
            ),
            model_usage=model_usage,
            models=[
                ModelUsageBreakdown(
                    provider=provider,
                    model=model,
                    tokens=int(total["tokens"]),
                    cost_usd=round(float(total["cost_usd"]), 6),
                    calls=int(total["calls"]),
                )
                for (provider, model), total in sorted(model_totals.items())
            ],
            recent_failures=[
                RecentFailure(
                    run_id=run.id,
                    title=run.title,
                    error=run.error_message or "Task execution failed.",
                    occurred_at=(run.finished_at or run.updated_at).replace(tzinfo=UTC).isoformat(),
                )
                for run in recent_failures
            ],
            slo=slo,
        )
