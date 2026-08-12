"""Integration contract from approval queueing through worker result persistence."""

from __future__ import annotations

import pytest

from app.core.events import EventBroker
from app.core.jobs import MemoryJobStore, RunQueue
from app.core.config import settings


@pytest.fixture
async def auth_headers(client):
    await client.post(
        "/api/v1/auth/register",
        json={
            "username": "closure-user",
            "email": "closure@example.com",
            "password": "Str0ngPwd!",
        },
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={
            "username": "closure-user",
            "password": "Str0ngPwd!",
        },
    )
    token = login.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    space = await client.post(
        "/api/v1/spaces", headers=headers, json={"name": "Closure Space"}
    )
    return {**headers, "X-Space-Id": str(space.json()["data"]["id"])}


@pytest.mark.asyncio
async def test_approval_enqueues_and_worker_callback_persists_outputs(client, auth_headers):
    repository = (
        await client.post(
            "/api/v1/repositories",
            headers=auth_headers,
            json={
                "name": "worker-closure",
                "path": "C:/repos/worker-closure",
                "default_branch": "main",
                "settings": {"test_command": "pytest -q"},
            },
        )
    ).json()["data"]
    assert repository["path"] == "C:/repos/worker-closure"

    run = (
        await client.post(
            "/api/v1/task-runs",
            headers=auth_headers,
            json={
                "repository_id": repository["id"],
                "title": "Complete worker closure",
                "prompt": "Implement the change, run focused tests, and return a diff.",
                "permission_mode": "full",
            },
        )
    ).json()["data"]
    approval = (
        await client.get(f"/api/v1/tasks/{run['id']}/approvals", headers=auth_headers)
    ).json()["data"][0]
    assert approval["kind"] == "plan"
    decided = await client.post(
        f"/api/v1/tasks/{run['id']}/approvals",
        headers=auth_headers,
        json={"approval_id": approval["id"], "decision": "approved"},
    )
    assert decided.json()["data"]["status"] == "approved"
    queued = (await client.get(f"/api/v1/task-runs/{run['id']}", headers=auth_headers)).json()[
        "data"
    ]
    assert queued["status"] == "queued"
    queue_store = RunQueue.default().store
    assert isinstance(queue_store, MemoryJobStore)
    assert queue_store.jobs[-1].run_id == str(run["id"])
    assert queue_store.jobs[-1].test_command == "pytest -q"

    payload = {
        "run_id": str(run["id"]),
        "status": "succeeded",
        "summary": "Focused verification passed.",
        "task_type": "bugfix",
        "plan": ["Inspect failing test", "Patch implementation", "Run tests"],
        "artifacts": [{"kind": "report", "path": "reports/review.md", "description": "review"}],
        "test_command": "pytest -q",
        "test_exit_code": 0,
        "diff": "diff --git a/app.py b/app.py\n+fixed = True\n",
        "events": [
            {
                "sequence": 0,
                "run_id": str(run["id"]),
                "event": "model_turn",
                "data": {
                    "model": "test-model",
                    "prompt_tokens": 80,
                    "completion_tokens": 20,
                    "cost_usd": 0.002,
                },
            },
            {
                "sequence": 1,
                "run_id": str(run["id"]),
                "event": "tool_result",
                "data": {
                    "call_id": "call-1",
                    "tool": "run_tests",
                    "arguments": {"command": "pytest -q"},
                    "status": "succeeded",
                    "summary": "12 passed",
                    "result": {
                        "status": "succeeded",
                        "summary": "12 passed",
                        "data": {"exit_code": 0},
                        "next_actions": ["review diff"],
                        "artifacts": [{"kind": "test_report", "path": "report.json"}],
                        "root_cause": None,
                        "retry": None,
                        "stop_condition": None,
                    },
                },
            }
        ],
    }
    callback = await client.post(
        f"/api/v1/internal/task-runs/{run['id']}/result",
        headers={"X-Worker-Token": settings.WORKER_CALLBACK_TOKEN},
        json=payload,
    )
    assert callback.status_code == 200
    assert callback.json()["data"]["status"] == "succeeded"
    replayed_callback = await client.post(
        f"/api/v1/internal/task-runs/{run['id']}/result",
        headers={"X-Worker-Token": settings.WORKER_CALLBACK_TOKEN},
        json=payload,
    )
    assert replayed_callback.status_code == 200
    completed = (
        await client.get(f"/api/v1/task-runs/{run['id']}", headers=auth_headers)
    ).json()["data"]
    assert completed["verification"]["model_usage"] == {
        "prompt_tokens": 80,
        "completion_tokens": 20,
        "cost_usd": 0.002,
        "models": [
            {
                "provider": "deepseek",
                "model": "test-model",
                "tokens": 100,
                "cost_usd": 0.002,
                "calls": 1,
            }
        ],
    }

    diff = (await client.get(f"/api/v1/tasks/{run['id']}/diff", headers=auth_headers)).json()[
        "data"
    ]
    assert diff["content"].startswith("diff --git")
    assert diff["verified"] is True
    tests = (await client.get(f"/api/v1/tasks/{run['id']}/tests", headers=auth_headers)).json()[
        "data"
    ]
    assert tests[0]["status"] == "passed"
    artifacts = (
        await client.get(f"/api/v1/tasks/{run['id']}/artifacts", headers=auth_headers)
    ).json()["data"]
    assert {item["kind"] for item in artifacts} >= {"diff", "test_report", "log", "report"}
    assert len(artifacts) == 4
    assert (
        len(
            (await client.get(f"/api/v1/tasks/{run['id']}/steps", headers=auth_headers)).json()[
                "data"
            ]
        )
        == 3
    )
    tools = (
        await client.get(f"/api/v1/tasks/{run['id']}/tool-invocations", headers=auth_headers)
    ).json()["data"]
    assert tools[0]["result"]["summary"] == "12 passed"
    assert tools[0]["input"] == {"command": "pytest -q", "_call_id": "call-1"}
    assert tools[0]["result"]["data"] == {"exit_code": 0}
    assert tools[0]["result"]["artifacts"][0]["path"] == "report.json"
    assert any(
        item.event == "result.persisted"
        for item in await EventBroker.default().read(str(run["id"]), after="0-0", block_ms=0)
    )
    requested = await client.post(
        f"/api/v1/task-runs/{run['id']}/approvals",
        headers=auth_headers,
        json={"operation": "git_publish"},
    )
    assert requested.status_code == 200
    publish_approval = requested.json()["data"]
    await client.post(
        f"/api/v1/approvals/{publish_approval['id']}/decision",
        headers=auth_headers,
        json={"decision": "approved"},
    )
    publish_job = queue_store.jobs[-1]
    assert publish_job.ops_capabilities == '["git_publish"]'
    assert publish_job.network_capabilities == '["git_publish"]'
    assert publish_job.clone_approved == "false"


@pytest.mark.asyncio
async def test_rejecting_git_publish_keeps_succeeded_run(client, auth_headers):
    repository = (
        await client.post(
            "/api/v1/repositories",
            headers=auth_headers,
            json={"name": "publish-reject", "root_path": "C:/work/publish-reject"},
        )
    ).json()["data"]
    run = (
        await client.post(
            "/api/v1/task-runs",
            headers=auth_headers,
            json={
                "repository_id": repository["id"],
                "title": "Reject publish",
                "prompt": "Implement a small change and leave a verified diff.",
                "permission_mode": "full",
            },
        )
    ).json()["data"]
    start = (
        await client.get(f"/api/v1/task-runs/{run['id']}/approvals", headers=auth_headers)
    ).json()["data"][0]
    await client.post(
        f"/api/v1/approvals/{start['id']}/decision",
        headers=auth_headers,
        json={"decision": "approved"},
    )
    from app.core.config import settings

    callback = await client.post(
        f"/api/v1/internal/task-runs/{run['id']}/result",
        headers={"X-Worker-Token": settings.WORKER_CALLBACK_TOKEN},
        json={
            "run_id": str(run["id"]),
            "status": "succeeded",
            "summary": "done",
            "task_type": "bugfix",
            "plan": ["edit"],
            "artifacts": [],
            "test_command": None,
            "test_exit_code": 0,
            "diff": "diff --git a/a.py b/a.py\n+ok\n",
            "events": [],
        },
    )
    assert callback.json()["data"]["status"] == "succeeded"
    requested = await client.post(
        f"/api/v1/task-runs/{run['id']}/approvals",
        headers=auth_headers,
        json={"operation": "git_publish"},
    )
    assert requested.status_code == 200
    rejected = await client.post(
        f"/api/v1/approvals/{requested.json()['data']['id']}/decision",
        headers=auth_headers,
        json={"decision": "rejected", "comment": "not now"},
    )
    assert rejected.json()["data"]["status"] == "rejected"
    current = (
        await client.get(f"/api/v1/task-runs/{run['id']}", headers=auth_headers)
    ).json()["data"]
    assert current["status"] == "succeeded"


@pytest.mark.asyncio
async def test_worker_callback_rejects_missing_token(client):
    response = await client.post(
        "/api/v1/internal/task-runs/1/result",
        json={
            "run_id": "1",
            "status": "failed",
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_remote_repository_requires_network_clone_approval(client, auth_headers):
    repository = (
        await client.post(
            "/api/v1/repositories",
            headers=auth_headers,
            json={
                "name": "remote-only",
                "clone_url": "https://example.invalid/private.git",
            },
        )
    ).json()["data"]
    run = (
        await client.post(
            "/api/v1/task-runs",
            headers=auth_headers,
            json={
                "repository_id": repository["id"],
                "title": "Inspect remote repository",
                "prompt": "Inspect the remote repository and report the relevant implementation.",
                "permission_mode": "read_only",
            },
        )
    ).json()["data"]
    approval = (
        await client.get(f"/api/v1/task-runs/{run['id']}/approvals", headers=auth_headers)
    ).json()["data"][0]
    assert approval["operation"] == "execute_task_network_clone"
    assert "network" in approval["reason"].lower()
    await client.post(
        f"/api/v1/approvals/{approval['id']}/decision",
        headers=auth_headers,
        json={"decision": "approved"},
    )
    queue_store = RunQueue.default().store
    assert isinstance(queue_store, MemoryJobStore)
    job = queue_store.jobs[-1]
    assert job.clone_approved == "true"
    assert job.network_approved == "false"
    assert job.network_capabilities == "[]"
    assert job.approved == "true"
    assert job.ops_approved == "false"


@pytest.mark.asyncio
async def test_local_run_approval_does_not_grant_ops(client, auth_headers):
    repository = (
        await client.post(
            "/api/v1/repositories",
            headers=auth_headers,
            json={"name": "local-repo", "root_path": "C:/work/local-repo"},
        )
    ).json()["data"]
    run = (
        await client.post(
            "/api/v1/task-runs",
            headers=auth_headers,
            json={
                "repository_id": repository["id"],
                "title": "Local edit",
                "prompt": "Fix a small bug.",
                "permission_mode": "edit",
            },
        )
    ).json()["data"]
    approval = (
        await client.get(f"/api/v1/task-runs/{run['id']}/approvals", headers=auth_headers)
    ).json()["data"][0]
    await client.post(
        f"/api/v1/approvals/{approval['id']}/decision",
        headers=auth_headers,
        json={"decision": "approved"},
    )
    job = RunQueue.default().store.jobs[-1]
    assert job.approved == "true"
    assert job.ops_approved == "false"
    assert job.network_approved == "false"


@pytest.mark.asyncio
async def test_interrupt_sets_worker_control_flag(client, auth_headers):
    from app.core.redis_client import RedisClient

    repository = (
        await client.post(
            "/api/v1/repositories",
            headers=auth_headers,
            json={"name": "interrupt-repo", "root_path": "C:/work/interrupt"},
        )
    ).json()["data"]
    run = (
        await client.post(
            "/api/v1/task-runs",
            headers=auth_headers,
            json={
                "repository_id": repository["id"],
                "title": "Interrupt me",
                "prompt": "Long running task",
                "permission_mode": "read_only",
            },
        )
    ).json()["data"]
    approval = (
        await client.get(f"/api/v1/task-runs/{run['id']}/approvals", headers=auth_headers)
    ).json()["data"][0]
    await client.post(
        f"/api/v1/approvals/{approval['id']}/decision",
        headers=auth_headers,
        json={"decision": "approved"},
    )
    interrupted = await client.post(
        f"/api/v1/task-runs/{run['id']}/interrupt", headers=auth_headers
    )
    assert interrupted.json()["data"]["status"] == "interrupted"
    redis = await RedisClient.get()
    assert await redis.get(f"run:control:{run['id']}") == "stop"
