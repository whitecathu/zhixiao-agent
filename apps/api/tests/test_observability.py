from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from prometheus_client import generate_latest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.exceptions import register_exception_handlers
from app.core.metrics import (
    METRICS_REGISTRY,
    PrometheusMiddleware,
    record_model_usage,
    record_tool_invocation,
)
from app.core.middleware import get_current_user, get_space_id
from app.db.session import get_session
from app.model.knowledge import ToolInvocation
from app.model.platform import Approval, Repository, TaskRun
from app.model.user import Space, SpaceMember, User
from app.router.observability import router
from app.service.observability_service import ObservabilityService, _percentile


def test_percentile_uses_nearest_rank() -> None:
    assert _percentile([], 0.95) == 0.0
    assert _percentile([1, 9, 2, 3], 0.5) == 2
    assert _percentile([1, 9, 2, 3], 0.95) == 9


def test_metric_dimensions_are_bounded_and_never_echo_sensitive_input() -> None:
    secret = "C:/private/repos/acme?token=very-secret"
    record_tool_invocation(secret, secret, 0.1)
    record_model_usage(secret, prompt_tokens=2, completion_tokens=3, cost_usd=0.01)

    payload = generate_latest(METRICS_REGISTRY).decode()
    assert secret not in payload
    assert 'category="other",status="other"' in payload
    assert 'provider="other"' in payload


@pytest.mark.asyncio
async def test_middleware_uses_route_template_instead_of_concrete_path() -> None:
    app = FastAPI()
    app.add_middleware(PrometheusMiddleware)

    @app.get("/items/{item_id}")
    async def item(item_id: str) -> dict[str, str]:
        return {"id": item_id}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/items/sensitive-repository-name")).status_code == 200

    payload = generate_latest(METRICS_REGISTRY).decode()
    assert 'route="/items/{item_id}"' in payload
    assert "sensitive-repository-name" not in payload


@pytest.mark.asyncio
async def test_space_summary_aggregates_runs_tools_approvals_and_slo(session) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    repository = Repository(space_id=7, owner_id=1, name="repo", status="ready")
    session.add(repository)
    await session.flush()
    succeeded = TaskRun(
        space_id=7,
        user_id=1,
        repository_id=repository.id,
        title="success",
        prompt="not returned by summary",
        status="succeeded",
        started_at=now - timedelta(seconds=100),
        finished_at=now,
        verification={
            "passed": True,
            "attempts": 1,
            "model_usage": {
                "prompt_tokens": 120,
                "completion_tokens": 30,
                "cost_usd": 0.0042,
                "models": [
                    {
                        "provider": "deepseek",
                        "model": "deepseek-chat",
                        "tokens": 150,
                        "cost_usd": 0.0042,
                        "calls": 1,
                    }
                ],
            },
        },
    )
    failed = TaskRun(
        space_id=7,
        user_id=1,
        repository_id=repository.id,
        title="failed",
        prompt="not returned by summary",
        status="failed",
        started_at=now - timedelta(seconds=10),
        finished_at=now,
        verification={"passed": False, "attempts": 2},
    )
    queued = TaskRun(
        space_id=7,
        user_id=1,
        repository_id=repository.id,
        title="queued",
        prompt="not returned by summary",
        status="queued",
    )
    session.add_all([succeeded, failed, queued])
    await session.flush()
    session.add_all(
        [
            ToolInvocation(
                task_run_id=succeeded.id,
                agent_name="tester",
                tool_name="run_tests",
                status="succeeded",
                success=1,
                duration_ms=500,
            ),
            ToolInvocation(
                task_run_id=failed.id,
                agent_name="implementer",
                tool_name="exact_edit",
                status="failed",
                success=0,
                duration_ms=1500,
            ),
            Approval(
                task_run_id=succeeded.id,
                operation="execute_task",
                reason="plan",
                requested_by=1,
                decided_by=1,
                status="approved",
                decided_at=now,
                created_at=now - timedelta(seconds=20),
            ),
            Approval(
                task_run_id=queued.id,
                operation="execute_task",
                reason="plan",
                requested_by=1,
                status="pending",
            ),
        ]
    )
    await session.commit()

    result = await ObservabilityService(session).summary(7)

    assert result.tasks.total == 3
    assert result.tasks.success_rate == 0.5
    assert result.tasks.first_pass_rate == 0.5
    assert result.tasks.p95_duration_seconds == 100
    assert result.queue_backlog == 1
    assert result.tools.total == 2
    assert result.tools.success_rate == 0.5
    assert result.approvals.pending == 1
    assert result.approvals.average_wait_seconds == 20
    assert result.model_usage.prompt_tokens == 120
    assert result.model_usage.cost_usd == 0.0042
    assert result.slo.cost_usd == 0.0042
    assert result.models[0].calls == 1
    assert result.recent_failures[0].run_id == failed.id


@pytest.mark.asyncio
async def test_summary_requires_real_space_admin_membership(engine) -> None:
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all(
            [
                User(
                    username="member",
                    email="member@example.com",
                    password_hash="unused",
                    status=1,
                ),
                Space(name="ops", owner_id=99),
            ]
        )
        await session.flush()
        session.add(SpaceMember(space_id=1, user_id=1, role="member"))
        await session.commit()

    async def test_session():
        async with factory() as session:
            yield session

    async def test_user() -> dict:
        return {"user_id": 1, "jti": "test", "payload": {"role": "member"}}

    async def test_space() -> int:
        return 1

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_session] = test_session
    app.dependency_overrides[get_current_user] = test_user
    app.dependency_overrides[get_space_id] = test_space
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        denied = await client.get("/api/v1/observability/summary")
        assert denied.status_code == 403

        async with factory() as session:
            membership = await session.scalar(
                select(SpaceMember).where(
                    SpaceMember.space_id == 1, SpaceMember.user_id == 1
                )
            )
            assert membership is not None
            membership.role = "space_admin"
            await session.commit()

        allowed = await client.get("/api/v1/observability/summary")
        assert allowed.status_code == 200
        assert allowed.json()["data"]["window"] == "24h"
        assert allowed.json()["data"]["slo"]["cost_usd"] is None
        assert (await client.get("/api/v1/observability/summary?window=invalid")).status_code == 422


@pytest.mark.asyncio
async def test_metrics_endpoint_is_internal_and_does_not_require_space_header() -> None:
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "zhixiao_api_requests_total" in response.text
