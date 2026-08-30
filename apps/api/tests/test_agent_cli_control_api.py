"""Task-run session controls, budgets, filters, and safe MCP configuration."""

from __future__ import annotations

import json

import pytest

from app.core.jobs import MemoryJobStore, RunQueue


@pytest.fixture
async def control_headers(client):
    await client.post(
        "/api/v1/auth/register",
        json={
            "username": "control-owner",
            "email": "control@example.com",
            "password": "Str0ngPwd!",
        },
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "control-owner", "password": "Str0ngPwd!"},
    )
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}
    space = await client.post(
        "/api/v1/spaces", headers=headers, json={"name": "Agent CLI Control"}
    )
    return {**headers, "X-Space-Id": str(space.json()["data"]["id"])}


async def _repository(client, headers, name="control-repo"):
    response = await client.post(
        "/api/v1/repositories",
        headers=headers,
        json={"name": name, "root_path": f"C:/repos/{name}"},
    )
    assert response.status_code == 200
    return response.json()["data"]


@pytest.mark.asyncio
async def test_run_budget_is_persisted_enqueued_and_forked(client, control_headers):
    store = MemoryJobStore()
    RunQueue._default = RunQueue(store)
    repository = await _repository(client, control_headers)
    created = await client.post(
        "/api/v1/task-runs",
        headers=control_headers,
        json={
            "repository_id": repository["id"],
            "title": "Budgeted repair",
            "prompt": "Repair the failing endpoint and run focused checks.",
            "permission_mode": "execute",
            "session_name": "api-fix",
            "budget": {
                "max_model_turns": 7,
                "max_tool_calls": 11,
                "max_tokens": 12000,
                "max_cost_usd": 1.25,
                "max_duration_seconds": 300,
            },
            "allow_unverified": "Browser is unavailable in this CI lane",
            "verification_commands": ["pytest -q", "ruff check ."],
        },
    )
    assert created.status_code == 200
    run = created.json()["data"]
    assert run["budget_snapshot"]["max_tool_calls"] == 11
    assert run["usage_snapshot"] == {}

    approvals = await client.get(
        f"/api/v1/task-runs/{run['id']}/approvals", headers=control_headers
    )
    approval_id = approvals.json()["data"][0]["id"]
    approved = await client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        headers=control_headers,
        json={"decision": "approved"},
    )
    assert approved.status_code == 200
    job = store.jobs[0]
    assert job.max_model_turns == "7"
    assert job.max_cost_usd == "1.25"
    assert json.loads(job.verification_commands) == ["pytest -q", "ruff check ."]
    assert job.allow_unverified == "Browser is unavailable in this CI lane"

    forked = await client.post(
        f"/api/v1/task-runs/{run['id']}/fork",
        headers=control_headers,
        json={"title": "Budgeted repair retry", "session_name": "api-fix-2"},
    )
    assert forked.status_code == 200
    child = forked.json()["data"]
    assert child["parent_run_id"] == run["id"]
    assert child["status"] == "awaiting_approval"
    assert child["budget_snapshot"] == run["budget_snapshot"]
    assert child["usage_snapshot"] == {}
    assert child["verification_commands"] == ["pytest -q", "ruff check ."]
    child_approvals = await client.get(
        f"/api/v1/task-runs/{child['id']}/approvals", headers=control_headers
    )
    assert len(child_approvals.json()["data"]) == 1


@pytest.mark.asyncio
async def test_run_filters_status_time_and_workspace(client, control_headers):
    repository = await _repository(client, control_headers, "filter-repo")
    run = (
        await client.post(
            "/api/v1/task-runs",
            headers=control_headers,
            json={
                "repository_id": repository["id"],
                "title": "Filter candidate",
                "prompt": "Inspect the repository without modifying files.",
                "permission_mode": "read_only",
            },
        )
    ).json()["data"]
    workspace = (
        await client.post(
            f"/api/v1/repositories/{repository['id']}/workspaces",
            headers=control_headers,
            json={
                "task_run_id": run["id"],
                "root_path": "C:/work/filter-run",
                "branch_name": "agent/filter-run",
            },
        )
    ).json()["data"]

    filtered = await client.get(
        "/api/v1/task-runs",
        headers=control_headers,
        params={
            "workspace_id": workspace["id"],
            "status": "awaiting_approval",
            "created_from": "2020-01-01T00:00:00",
            "created_to": "2100-01-01T00:00:00",
        },
    )
    assert [item["id"] for item in filtered.json()["data"]] == [run["id"]]
    invalid_range = await client.get(
        "/api/v1/task-runs",
        headers=control_headers,
        params={
            "created_from": "2100-01-01T00:00:00",
            "created_to": "2020-01-01T00:00:00",
        },
    )
    assert invalid_range.status_code == 422


@pytest.mark.asyncio
async def test_mcp_crud_and_test_are_secret_free_and_side_effect_free(
    client, control_headers, monkeypatch
):
    def forbidden(*args, **kwargs):
        raise AssertionError("MCP validation must not execute commands or network calls")

    monkeypatch.setattr("subprocess.run", forbidden)
    created = await client.post(
        "/api/v1/mcp-servers",
        headers=control_headers,
        json={
            "name": "workspace-tools",
            "transport": "stdio",
            "command": "trusted-mcp-wrapper",
            "arguments": ["--stdio"],
            "env_refs": {"GITHUB_TOKEN": "GITHUB_TOKEN"},
            "credential_env": "GITHUB_TOKEN",
            "tool_allowlist": ["read_repository"],
        },
    )
    assert created.status_code == 200
    server = created.json()["data"]
    assert "secret" not in json.dumps(server).lower()
    assert (await client.get("/api/v1/mcp-servers", headers=control_headers)).status_code == 200

    diagnosis = await client.post(
        f"/api/v1/mcp-servers/{server['id']}/test", headers=control_headers
    )
    assert diagnosis.status_code == 200
    assert diagnosis.json()["data"]["network_attempted"] is False
    assert diagnosis.json()["data"]["command_executed"] is False

    updated = await client.put(
        f"/api/v1/mcp-servers/{server['id']}",
        headers=control_headers,
        json={"call_timeout_seconds": 90, "enabled": False},
    )
    assert updated.json()["data"]["call_timeout_seconds"] == 90
    deleted = await client.delete(
        f"/api/v1/mcp-servers/{server['id']}", headers=control_headers
    )
    assert deleted.json()["data"] == {"id": server["id"], "deleted": True}
    assert (await client.get("/api/v1/mcp-servers", headers=control_headers)).json()[
        "data"
    ] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {
            "name": "loopback",
            "transport": "streamable_http",
            "url": "https://127.0.0.1/mcp",
        },
        {
            "name": "embedded-credential",
            "transport": "streamable_http",
            "url": "https://user:password@example.com/mcp",
        },
        {
            "name": "literal-secret",
            "transport": "stdio",
            "command": "mcp",
            "env_refs": {"TOKEN": "not-a-valid-env-reference"},
        },
    ],
)
async def test_mcp_rejects_ssrf_credentials_and_literal_env_values(
    client, control_headers, payload
):
    response = await client.post(
        "/api/v1/mcp-servers", headers=control_headers, json=payload
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_worker_callback_persists_structured_outcome(client, control_headers):
    repository = await _repository(client, control_headers, "callback-repo")
    run = (
        await client.post(
            "/api/v1/task-runs",
            headers=control_headers,
            json={
                "repository_id": repository["id"],
                "title": "Persist callback",
                "prompt": "Inspect callback persistence without editing source files.",
                "permission_mode": "read_only",
            },
        )
    ).json()["data"]
    callback = await client.post(
        f"/api/v1/internal/task-runs/{run['id']}/result",
        headers={"X-Worker-Token": "test-worker-token-at-least-24-chars"},
        json={
            "schema_version": "1.1",
            "run_id": str(run["id"]),
            "status": "failed",
            "summary": "Token budget exhausted",
            "verification": {
                "outcome": "blocked",
                "reason": "Budget exhausted before verification",
                "waived": False,
            },
            "termination_reason": "budget_exhausted",
            "usage": {"model_turns": 3, "prompt_tokens": 1200, "cost_usd": 0.12},
            "budgets": {
                "max_model_turns": 3,
                "max_tool_calls": 10,
                "max_tokens": 1000,
                "max_cost_usd": None,
                "max_duration_seconds": 300,
            },
            "next_actions": ["Increase the token budget and fork the run"],
            "events": [],
            "error": "maximum token budget exceeded",
        },
    )
    assert callback.status_code == 200
    persisted = callback.json()["data"]
    assert persisted["termination_reason"] == "budget_exhausted"
    assert persisted["usage_snapshot"]["prompt_tokens"] == 1200
    assert persisted["budget_snapshot"]["max_model_turns"] == 3
    assert persisted["verification"]["details"]["outcome"] == "blocked"
    assert persisted["verification"]["next_actions"] == [
        "Increase the token budget and fork the run"
    ]


@pytest.mark.asyncio
async def test_write_run_cannot_report_success_without_verification_or_waiver(
    client, control_headers
):
    repository = await _repository(client, control_headers, "unverified-callback-repo")
    run = (
        await client.post(
            "/api/v1/task-runs",
            headers=control_headers,
            json={
                "repository_id": repository["id"],
                "title": "Reject false success",
                "prompt": "Implement a source change and verify it before completion.",
                "permission_mode": "edit",
            },
        )
    ).json()["data"]

    callback = await client.post(
        f"/api/v1/internal/task-runs/{run['id']}/result",
        headers={"X-Worker-Token": "test-worker-token-at-least-24-chars"},
        json={
            "run_id": str(run["id"]),
            "status": "succeeded",
            "summary": "claimed completion",
            "diff": "diff --git a/app.py b/app.py\n+changed = True\n",
            "events": [],
        },
    )

    assert callback.status_code == 200
    persisted = callback.json()["data"]
    assert persisted["status"] == "failed"
    assert persisted["termination_reason"] == "verification_blocked"
    assert persisted["verification"]["passed"] is False
