"""Legacy task API remains usable through the injected execution adapter."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_create_interrupt_and_resume_legacy_task(client):
    await client.post("/api/v1/auth/register", json={
        "username": "task-user",
        "email": "task@example.com",
        "password": "Str0ngPwd!",
    })
    login = await client.post("/api/v1/auth/login", json={
        "username": "task-user", "password": "Str0ngPwd!",
    })
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}
    space = await client.post(
        "/api/v1/spaces", headers=headers, json={"name": "Task Space"}
    )
    headers["X-Space-Id"] = str(space.json()["data"]["id"])
    created = await client.post("/api/v1/tasks", headers=headers, json={
        "title": "Fix tests",
        "goal": "Fix the failing tests and provide verification evidence.",
    })
    assert created.status_code == 200
    assert created.headers["Deprecation"] == "true"
    assert "/api/v1/task-runs" in created.headers["Link"]
    task = created.json()["data"]
    assert task["status"] == "running"

    interrupted = await client.post(
        f"/api/v1/tasks/{task['id']}/control",
        headers=headers,
        json={"action": "interrupt"},
    )
    assert interrupted.json()["code"] == 0
    resumed = await client.post(
        f"/api/v1/tasks/{task['id']}/control",
        headers=headers,
        json={"action": "resume"},
    )
    assert resumed.json()["code"] == 0


@pytest.mark.asyncio
async def test_legacy_task_and_sse_openapi_operations_are_deprecated(client):
    schema = (await client.get("/openapi.json")).json()

    assert schema["paths"]["/api/v1/tasks"]["post"]["deprecated"] is True
    assert schema["paths"]["/sse/tasks/{task_id}"]["get"]["deprecated"] is True
    assert not schema["paths"]["/api/v1/task-runs"]["post"].get("deprecated", False)
