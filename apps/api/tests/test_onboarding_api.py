"""Onboarding persistence, replay, and space-role authorization tests."""

from __future__ import annotations

import pytest


async def _registered_headers(client, username: str) -> tuple[dict[str, str], int]:
    await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "Str0ngPwd!",
        },
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "Str0ngPwd!"},
    )
    token = login.json()["data"]["access_token"]
    user_id = login.json()["data"]["user"]["id"]
    return {"Authorization": f"Bearer {token}"}, user_id


@pytest.mark.asyncio
async def test_onboarding_can_complete_skip_and_replay(client):
    headers, _ = await _registered_headers(client, "onboarding-owner")
    space = (
        await client.post(
            "/api/v1/spaces",
            headers=headers,
            json={"name": "Onboarding", "description": "First run"},
        )
    ).json()["data"]
    headers["X-Space-Id"] = str(space["id"])

    state = (await client.get("/api/v1/onboarding/me", headers=headers)).json()["data"]
    assert state["current_step"] == "select_space"
    assert not state["finished"]

    completed = (
        await client.post(
            "/api/v1/onboarding/me/steps/select_space/complete", headers=headers
        )
    ).json()["data"]
    assert completed["completed_steps"] == ["select_space"]
    assert completed["current_step"] == "connect_repository"

    skipped = (
        await client.post("/api/v1/onboarding/me/skip", headers=headers)
    ).json()["data"]
    assert skipped["skipped"] and skipped["finished"]

    replayed = (
        await client.post("/api/v1/onboarding/me/replay", headers=headers)
    ).json()["data"]
    assert replayed["completed_steps"] == []
    assert replayed["replay_count"] == 1
    assert not replayed["finished"]


@pytest.mark.asyncio
async def test_onboarding_config_requires_space_admin(client):
    owner_headers, _ = await _registered_headers(client, "onboarding-admin")
    space = (
        await client.post(
            "/api/v1/spaces", headers=owner_headers, json={"name": "Admin Space"}
        )
    ).json()["data"]
    owner_headers["X-Space-Id"] = str(space["id"])

    member_headers, member_user_id = await _registered_headers(client, "onboarding-member")
    await client.post(
        f"/api/v1/spaces/{space['id']}/members",
        headers=owner_headers,
        json={"user_id": member_user_id, "role": "member"},
    )
    member_headers["X-Space-Id"] = str(space["id"])

    denied = await client.put(
        "/api/v1/onboarding/config",
        headers=member_headers,
        json={"recommended_template": "safe-fix"},
    )
    assert denied.status_code == 403

    updated = await client.put(
        "/api/v1/onboarding/config",
        headers=owner_headers,
        json={"recommended_template": "safe-fix"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["recommended_template"] == "safe-fix"


@pytest.mark.asyncio
async def test_onboarding_rejects_non_member_and_unknown_step(client):
    owner_headers, _ = await _registered_headers(client, "space-owner")
    space = (
        await client.post(
            "/api/v1/spaces", headers=owner_headers, json={"name": "Private Space"}
        )
    ).json()["data"]
    outsider_headers, _ = await _registered_headers(client, "space-outsider")
    outsider_headers["X-Space-Id"] = str(space["id"])
    assert (await client.get("/api/v1/onboarding/me", headers=outsider_headers)).status_code == 403

    owner_headers["X-Space-Id"] = str(space["id"])
    invalid = await client.post(
        "/api/v1/onboarding/me/steps/not-a-step/complete", headers=owner_headers
    )
    assert invalid.status_code == 422
