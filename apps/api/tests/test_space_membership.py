"""Regression tests for space membership enforcement and legacy SSE gating."""

from __future__ import annotations

import pytest


@pytest.fixture
async def member_headers(client):
    await client.post(
        "/api/v1/auth/register",
        json={
            "username": "space-owner",
            "email": "owner@example.com",
            "password": "Str0ngPwd!",
        },
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "space-owner", "password": "Str0ngPwd!"},
    )
    token = login.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    space = await client.post(
        "/api/v1/spaces", headers=headers, json={"name": "Owner Space"}
    )
    return {
        **headers,
        "X-Space-Id": str(space.json()["data"]["id"]),
        "space_id": space.json()["data"]["id"],
    }


@pytest.fixture
async def outsider_token(client):
    await client.post(
        "/api/v1/auth/register",
        json={
            "username": "space-outsider",
            "email": "outsider@example.com",
            "password": "Str0ngPwd!",
        },
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "space-outsider", "password": "Str0ngPwd!"},
    )
    return login.json()["data"]["access_token"]


@pytest.mark.asyncio
async def test_non_member_cannot_list_task_runs(client, member_headers, outsider_token):
    denied = await client.get(
        "/api/v1/task-runs",
        headers={
            "Authorization": f"Bearer {outsider_token}",
            "X-Space-Id": str(member_headers["space_id"]),
        },
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_legacy_sse_requires_space_membership_and_run(client, member_headers, outsider_token):
    repository = (
        await client.post(
            "/api/v1/repositories",
            headers={
                "Authorization": member_headers["Authorization"],
                "X-Space-Id": member_headers["X-Space-Id"],
            },
            json={"name": "sse-demo", "root_path": "C:/tmp/sse-demo"},
        )
    ).json()["data"]
    run = (
        await client.post(
            "/api/v1/task-runs",
            headers={
                "Authorization": member_headers["Authorization"],
                "X-Space-Id": member_headers["X-Space-Id"],
            },
            json={
                "repository_id": repository["id"],
                "title": "SSE gate",
                "prompt": "Inspect repository structure.",
                "permission_mode": "read_only",
            },
        )
    ).json()["data"]

    outsider = await client.get(
        f"/sse/tasks/{run['id']}",
        headers={
            "Authorization": f"Bearer {outsider_token}",
            "X-Space-Id": str(member_headers["space_id"]),
        },
    )
    assert outsider.status_code == 403

    missing_space = await client.get(
        f"/sse/tasks/{run['id']}",
        headers={"Authorization": member_headers["Authorization"]},
    )
    assert missing_space.status_code == 400
