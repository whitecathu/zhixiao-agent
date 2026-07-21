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
    headers = {
        "Authorization": f"Bearer {login.json()['data']['access_token']}",
        "X-Space-Id": "7",
    }
    created = await client.post("/api/v1/tasks", headers=headers, json={
        "title": "Fix tests",
        "goal": "Fix the failing tests and provide verification evidence.",
    })
    assert created.status_code == 200
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
