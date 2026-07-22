"""Integration contract from approval queueing through worker result persistence."""

from __future__ import annotations

import pytest

from app.core.events import EventBroker
from app.core.jobs import MemoryJobStore, RunQueue


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
    return {
        "Authorization": f"Bearer {login.json()['data']['access_token']}",
        "X-Space-Id": "1",
    }


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
                "permission_mode": "execute",
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
        headers={"X-Worker-Token": "test-worker-token"},
        json=payload,
    )
    assert callback.status_code == 200
    assert callback.json()["data"]["status"] == "succeeded"
    replayed_callback = await client.post(
        f"/api/v1/internal/task-runs/{run['id']}/result",
        headers={"X-Worker-Token": "test-worker-token"},
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
    assert queue_store.jobs[-1].network_approved == "true"
