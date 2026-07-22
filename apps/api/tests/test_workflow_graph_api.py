from __future__ import annotations

import json

import pytest

from app.core.jobs import MemoryJobStore, RunJob, RunQueue


def test_legacy_run_job_defaults_keep_workflow_fields_optional() -> None:
    fields = RunJob(run_id="1", prompt="inspect", permission_mode="read_only").fields()
    assert fields["workflow_definition"] == ""
    assert fields["workflow_version"] == ""


@pytest.fixture
async def auth_headers(client):
    await client.post(
        "/api/v1/auth/register",
        json={
            "username": "workflow-admin",
            "email": "workflow-admin@example.com",
            "password": "Str0ngPwd!",
        },
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "workflow-admin", "password": "Str0ngPwd!"},
    )
    headers = {
        "Authorization": f"Bearer {login.json()['data']['access_token']}",
    }
    space = await client.post(
        "/api/v1/spaces", headers=headers, json={"name": "Workflow Test Space"}
    )
    return {**headers, "X-Space-Id": str(space.json()["data"]["id"])}


def definition(*, second_role: str = "implementer") -> dict:
    return {
        "schema_version": 1,
        "entrypoint": "plan",
        "nodes": [
            {"id": "plan", "role": "planner", "position": {"x": 0, "y": 0}},
            {
                "id": "work",
                "role": second_role,
                "tool_allowlist": ["read_file", "exact_edit"],
                "retries": 1,
            },
        ],
        "edges": [{"source": "plan", "target": "work", "condition": "success"}],
    }


@pytest.mark.asyncio
async def test_workflow_publish_versions_and_task_binding(client, auth_headers):
    repository = (
        await client.post(
            "/api/v1/repositories",
            headers=auth_headers,
            json={"name": "workflow-repo", "root_path": "C:/repos/workflow"},
        )
    ).json()["data"]
    created = await client.post(
        "/api/v1/workflows",
        headers=auth_headers,
        json={"name": "engineering", "definition": definition()},
    )
    assert created.status_code == 200
    draft = created.json()["data"]
    assert draft["status"] == "draft"

    rejected = await client.post(
        "/api/v1/task-runs",
        headers=auth_headers,
        json={
            "repository_id": repository["id"],
            "workflow_id": draft["id"],
            "title": "Draft is unsafe",
            "prompt": "Attempt to execute an unpublished workflow version.",
        },
    )
    assert rejected.status_code == 409

    published = await client.post(
        f"/api/v1/workflows/{draft['id']}/publish", headers=auth_headers
    )
    assert published.status_code == 200
    assert published.json()["data"]["status"] == "published"
    assert published.json()["data"]["published_at"] is not None

    run = await client.post(
        "/api/v1/task-runs",
        headers=auth_headers,
        json={
            "repository_id": repository["id"],
            "workflow_id": draft["id"],
            "title": "Bound workflow",
            "prompt": "Execute the published workflow and preserve its exact version.",
        },
    )
    assert run.status_code == 200
    assert run.json()["data"]["workflow_version"] == 1
    approvals = await client.get(
        f"/api/v1/task-runs/{run.json()['data']['id']}/approvals", headers=auth_headers
    )
    await client.post(
        f"/api/v1/approvals/{approvals.json()['data'][0]['id']}/decision",
        headers=auth_headers,
        json={"decision": "approved"},
    )
    store = RunQueue.default().store
    assert isinstance(store, MemoryJobStore)
    queued = store.jobs[-1]
    assert queued.workflow_version == "1"
    assert json.loads(queued.workflow_definition)["nodes"][1]["role"] == "implementer"

    updated = await client.put(
        f"/api/v1/workflows/{draft['id']}",
        headers=auth_headers,
        json={"definition": definition(second_role="reviewer")},
    )
    assert updated.json()["data"]["version"] == 2
    assert updated.json()["data"]["status"] == "draft"
    versions = await client.get(
        f"/api/v1/workflows/{draft['id']}/versions", headers=auth_headers
    )
    assert [item["version"] for item in versions.json()["data"]] == [2, 1]
    replay = await client.get(
        f"/api/v1/task-runs/{run.json()['data']['id']}/workflow-replay",
        headers=auth_headers,
    )
    assert replay.json()["data"]["workflow"]["version"] == 1
    assert replay.json()["data"]["workflow"]["definition"]["nodes"][1]["role"] == "implementer"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_definition",
    [
        {
            "nodes": [{"id": "plan", "role": "planner"}],
            "edges": [{"source": "plan", "target": "missing"}],
        },
        {
            "nodes": [
                {"id": "one", "role": "planner"},
                {"id": "two", "role": "tester"},
            ],
            "edges": [
                {"source": "one", "target": "two"},
                {"source": "two", "target": "one"},
            ],
        },
        {
            "nodes": [
                {"id": "one", "role": "planner"},
                {"id": "orphan", "role": "tester"},
            ],
            "edges": [],
        },
    ],
)
async def test_workflow_rejects_invalid_graphs(client, auth_headers, invalid_definition):
    response = await client.post(
        "/api/v1/workflows",
        headers=auth_headers,
        json={"name": "invalid", "definition": invalid_definition},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_space_member_cannot_write_workflow_definitions(client, auth_headers):
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "workflow-member",
            "email": "workflow-member@example.com",
            "password": "Str0ngPwd!",
        },
    )
    await client.post(
        f"/api/v1/spaces/{auth_headers['X-Space-Id']}/members",
        headers=auth_headers,
        json={"user_id": registered.json()["data"]["id"], "role": "member"},
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "workflow-member", "password": "Str0ngPwd!"},
    )
    member_headers = {
        "Authorization": f"Bearer {login.json()['data']['access_token']}",
        "X-Space-Id": auth_headers["X-Space-Id"],
    }
    response = await client.post(
        "/api/v1/workflows",
        headers=member_headers,
        json={"name": "not-allowed", "definition": definition()},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_graph_explore_is_bounded_and_returns_evidence_state(client, auth_headers):
    source = (
        await client.post(
            "/api/v1/knowledge-entities",
            headers=auth_headers,
            json={
                "name": "TaskRun",
                "entity_type": "class",
                "source_refs": [{"path": "app/model/platform.py"}],
            },
        )
    ).json()["data"]
    target = (
        await client.post(
            "/api/v1/knowledge-entities",
            headers=auth_headers,
            json={"name": "WorkflowDefinition", "entity_type": "class"},
        )
    ).json()["data"]
    isolated = (
        await client.post(
            "/api/v1/knowledge-entities",
            headers=auth_headers,
            json={"name": "NoEvidence", "entity_type": "class"},
        )
    ).json()["data"]
    await client.post(
        "/api/v1/knowledge-relations",
        headers=auth_headers,
        json={
            "source_entity_id": source["id"],
            "target_entity_id": target["id"],
            "relation_type": "USES",
            "evidence": [{"path": "app/service/platform_service.py", "line": 200}],
        },
    )

    explored = await client.post(
        "/api/v1/knowledge/graph/explore",
        headers=auth_headers,
        json={"entity_id": source["id"], "depth": 1, "limit": 10},
    )
    data = explored.json()["data"]
    assert explored.status_code == 200
    assert {item["id"] for item in data["entities"]} == {source["id"], target["id"]}
    assert data["evidence_sufficient"] is True
    assert data["evidence_chain"][0]["evidence"][0]["path"].endswith("platform_service.py")

    no_evidence = await client.post(
        "/api/v1/knowledge/graph/explore",
        headers=auth_headers,
        json={"entity_id": isolated["id"], "depth": 1},
    )
    assert no_evidence.json()["data"]["evidence_status"] == "no_source_evidence"
    bounded = await client.post(
        "/api/v1/knowledge/graph/explore",
        headers=auth_headers,
        json={"depth": 0, "limit": 1},
    )
    assert len(bounded.json()["data"]["entities"]) == 1
    assert bounded.json()["data"]["truncated"] is True

    outside_space = await client.post(
        "/api/v1/knowledge/graph/explore",
        headers={**auth_headers, "X-Space-Id": "999"},
        json={"query": "TaskRun"},
    )
    assert outside_space.status_code == 403
