from __future__ import annotations

import pytest

from app.core.events import EventBroker


@pytest.fixture
async def auth_headers(client):
    await client.post(
        "/api/v1/auth/register",
        json={
            "username": "update-user",
            "email": "update@example.com",
            "password": "Str0ngPwd!",
        },
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={
            "username": "update-user",
            "password": "Str0ngPwd!",
        },
    )
    headers = {
        "Authorization": f"Bearer {login.json()['data']['access_token']}",
    }
    space = await client.post(
        "/api/v1/spaces", headers=headers, json={"name": "Platform Update Space"}
    )
    return {**headers, "X-Space-Id": str(space.json()["data"]["id"])}


@pytest.mark.asyncio
async def test_repository_index_probes_real_path(client, auth_headers, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / "README.md").write_text("demo", encoding="utf-8")
    repository = (
        await client.post(
            "/api/v1/repositories",
            headers=auth_headers,
            json={
                "name": "indexable",
                "path": str(tmp_path),
            },
        )
    ).json()["data"]
    response = await client.post(
        f"/api/v1/repositories/{repository['id']}/index", headers=auth_headers
    )
    assert response.status_code == 200
    indexed = response.json()["data"]
    assert indexed["status"] == "ready"
    assert indexed["settings"]["index"]["file_count"] == 2
    assert indexed["settings"]["index"]["top_extensions"] == {".py": 1, ".md": 1}
    events = await EventBroker.default().read(str(repository["id"]), "0-0", 0)
    assert events[-1].event == "repository.indexed"


@pytest.mark.asyncio
async def test_platform_definitions_support_safe_updates(client, auth_headers):
    workflow = (
        await client.post(
            "/api/v1/workflows",
            headers=auth_headers,
            json={
                "name": "engineering",
                "definition": {
                    "nodes": [{"id": "plan", "role": "planner"}],
                    "edges": [],
                },
            },
        )
    ).json()["data"]
    updated_workflow = await client.put(
        f"/api/v1/workflows/{workflow['id']}",
        headers=auth_headers,
        json={
            "definition": {
                "nodes": [
                    {"id": "plan", "role": "planner"},
                    {"id": "test", "role": "tester"},
                ],
                "edges": [{"source": "plan", "target": "test"}],
            }
        },
    )
    assert updated_workflow.status_code == 200
    assert updated_workflow.json()["data"]["version"] == 2
    workflows = (await client.get("/api/v1/workflows", headers=auth_headers)).json()["data"]
    assert sorted(item["version"] for item in workflows) == [1, 2]
    invalid = await client.put(
        f"/api/v1/workflows/{workflow['id']}",
        headers=auth_headers,
        json={"definition": {"nodes": [], "edges": []}},
    )
    assert invalid.status_code == 422

    model = (
        await client.post(
            "/api/v1/models",
            headers=auth_headers,
            json={
                "name": "primary",
                "provider": "openai",
                "base_url": "https://api.example/v1",
                "model_name": "model-a",
            },
        )
    ).json()["data"]
    model_update = await client.put(
        f"/api/v1/models/{model['id']}",
        headers=auth_headers,
        json={"model_name": "model-b", "enabled": False},
    )
    assert model_update.json()["data"]["model_name"] == "model-b"
    assert model_update.json()["data"]["enabled"] is False

    agent = (
        await client.post(
            "/api/v1/agents",
            headers=auth_headers,
            json={
                "name": "reviewer",
                "role": "reviewer",
                "system_prompt": "Review carefully.",
                "tool_allowlist": ["read_file"],
                "model_profile_id": model["id"],
            },
        )
    ).json()["data"]
    agent_update = await client.put(
        f"/api/v1/agents/{agent['id']}",
        headers=auth_headers,
        json={"system_prompt": "Review code and tests.", "tool_allowlist": ["read_file", "grep"]},
    )
    assert agent_update.json()["data"]["system_prompt"] == "Review code and tests."
    assert agent_update.json()["data"]["tool_allowlist"] == ["read_file", "grep"]
