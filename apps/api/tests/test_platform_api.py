"""Platform resource and task-run lifecycle contract tests."""
from __future__ import annotations

import pytest

from app.model.platform import TaskRun


def test_task_run_state_machine_rejects_terminal_resume():
    assert TaskRun.can_transition("awaiting_approval", "running")
    assert TaskRun.can_transition("running", "interrupted")
    assert TaskRun.can_transition("interrupted", "running")
    assert not TaskRun.can_transition("succeeded", "running")


@pytest.fixture
async def auth_headers(client):
    await client.post("/api/v1/auth/register", json={
        "username": "platform-user",
        "email": "platform@example.com",
        "password": "Str0ngPwd!",
    })
    login = await client.post("/api/v1/auth/login", json={
        "username": "platform-user",
        "password": "Str0ngPwd!",
    })
    token = login.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    space = await client.post(
        "/api/v1/spaces", headers=headers, json={"name": "Platform Test Space"}
    )
    return {**headers, "X-Space-Id": str(space.json()["data"]["id"])}


@pytest.mark.asyncio
async def test_repository_and_task_run_lifecycle(client, auth_headers):
    created = await client.post("/api/v1/repositories", headers=auth_headers, json={
        "name": "demo",
        "clone_url": "https://example.invalid/demo.git",
        "default_branch": "main",
    })
    assert created.status_code == 200
    repository = created.json()["data"]

    run = await client.post("/api/v1/task-runs", headers=auth_headers, json={
        "repository_id": repository["id"],
        "title": "Fix API",
        "prompt": "Fix the failing API test and verify the result.",
        "permission_mode": "edit",
    })
    assert run.status_code == 200
    run_data = run.json()["data"]
    assert run_data["status"] == "awaiting_approval"

    workspace = await client.post(
        f"/api/v1/repositories/{repository['id']}/workspaces",
        headers=auth_headers,
        json={
            "task_run_id": run_data["id"],
            "root_path": "C:/work/demo-run",
            "branch_name": "agent/run-1",
        },
    )
    assert workspace.json()["data"]["branch_name"] == "agent/run-1"

    approvals = await client.get(
        f"/api/v1/task-runs/{run_data['id']}/approvals", headers=auth_headers
    )
    approval = approvals.json()["data"][0]
    decided = await client.post(
        f"/api/v1/approvals/{approval['id']}/decision",
        headers=auth_headers,
        json={"decision": "approved", "comment": "Proceed"},
    )
    assert decided.json()["data"]["status"] == "approved"

    interrupted = await client.post(
        f"/api/v1/task-runs/{run_data['id']}/interrupt", headers=auth_headers
    )
    assert interrupted.json()["data"]["status"] == "interrupted"
    resumed = await client.post(
        f"/api/v1/task-runs/{run_data['id']}/resume", headers=auth_headers
    )
    assert resumed.json()["data"]["status"] == "queued"

    step = await client.post(
        f"/api/v1/tasks/{run_data['id']}/steps",
        headers=auth_headers,
        json={"sequence": 0, "role": "tester", "name": "pytest", "status": "succeeded"},
    )
    invocation = await client.post(
        f"/api/v1/tasks/{run_data['id']}/tool-invocations",
        headers=auth_headers,
        json={
            "run_step_id": step.json()["data"]["id"],
            "agent_name": "tester",
            "tool_name": "test",
            "input": {"command": "pytest -q"},
            "result": {
                "status": "succeeded",
                "summary": "15 tests passed",
                "next_actions": [],
                "artifacts": [],
            },
            "duration_ms": 120,
        },
    )
    assert invocation.json()["data"]["result"]["status"] == "succeeded"

    artifact = await client.post(
        f"/api/v1/tasks/{run_data['id']}/artifacts",
        headers=auth_headers,
        json={
            "kind": "test_report",
            "name": "pytest.json",
            "mime_type": "application/json",
            "size": 128,
            "metadata": {"passed": 17},
        },
    )
    assert artifact.json()["data"]["metadata"]["passed"] == 17
    artifacts = await client.get(
        f"/api/v1/tasks/{run_data['id']}/artifacts", headers=auth_headers
    )
    assert len(artifacts.json()["data"]) == 1
    diff = await client.get(f"/api/v1/tasks/{run_data['id']}/diff", headers=auth_headers)
    assert diff.json()["data"] == {
        "task_run_id": run_data["id"], "unified_diff": "", "content": "",
        "verified": False,
    }
    assert len((await client.get("/api/v1/task-runs", headers=auth_headers)).json()["data"]) == 1
    fetched = await client.get(f"/api/v1/task-runs/{run_data['id']}", headers=auth_headers)
    assert fetched.json()["data"]["id"] == run_data["id"]


@pytest.mark.asyncio
async def test_configuration_resources_and_graph(client, auth_headers):
    repository = await client.post("/api/v1/repositories", headers=auth_headers, json={
        "name": "config-repo", "root_path": "C:/repos/config", "default_branch": "main",
    })
    assert len((await client.get("/api/v1/repositories", headers=auth_headers)).json()["data"]) == 1

    workflow = await client.post("/api/v1/workflows", headers=auth_headers, json={
        "name": "safe-edit",
        "version": 1,
        "definition": {"nodes": [{"id": "plan", "type": "planner"}], "edges": []},
    })
    assert workflow.json()["data"]["definition"]["nodes"][0]["id"] == "plan"

    model = await client.post("/api/v1/models", headers=auth_headers, json={
        "name": "local",
        "provider": "vllm",
        "base_url": "http://localhost:8001/v1",
        "model_name": "test-model",
    })
    assert model.json()["data"]["provider"] == "vllm"

    agent = await client.post("/api/v1/agents", headers=auth_headers, json={
        "name": "reviewer",
        "role": "reviewer",
        "system_prompt": "Review changes and report actionable findings.",
        "tool_allowlist": ["read_file", "search", "git_diff"],
        "model_profile_id": model.json()["data"]["id"],
    })
    assert agent.json()["data"]["role"] == "reviewer"
    assert len((await client.get("/api/v1/agents", headers=auth_headers)).json()["data"]) == 1
    assert len((await client.get("/api/v1/models", headers=auth_headers)).json()["data"]) == 1
    tools = (await client.get("/api/v1/tools", headers=auth_headers)).json()["data"]
    assert any(item["name"] == "run_tests" for item in tools)
    assert any(item["name"] == "exact_edit" for item in tools)

    evaluation = await client.post("/api/v1/evaluations", headers=auth_headers, json={
        "dataset_name": "smoke-v1", "model_profile_id": model.json()["data"]["id"],
    })
    assert evaluation.json()["data"]["status"] == "queued"
    assert len((await client.get("/api/v1/evaluations", headers=auth_headers)).json()["data"]) == 1

    fine_tune = await client.post("/api/v1/fine-tunes", headers=auth_headers, json={
        "base_model": "tiny-test-model", "config": {"rank": 8},
    })
    assert fine_tune.json()["data"]["config"]["rank"] == 8
    assert len((await client.get("/api/v1/fine-tunes", headers=auth_headers)).json()["data"]) == 1

    entity = await client.post("/api/v1/knowledge-entities", headers=auth_headers, json={
        "name": "TaskRun",
        "entity_type": "class",
        "properties": {"module": "app.model.platform"},
    })
    assert entity.json()["data"]["name"] == "TaskRun"
    target = await client.post("/api/v1/knowledge-entities", headers=auth_headers, json={
        "name": "Repository", "entity_type": "class", "properties": {},
    })
    relation = await client.post("/api/v1/knowledge-relations", headers=auth_headers, json={
        "source_entity_id": entity.json()["data"]["id"],
        "target_entity_id": target.json()["data"]["id"],
        "relation_type": "BELONGS_TO",
        "evidence": [{"source": "app/model/platform.py"}],
    })
    assert relation.json()["data"]["relation_type"] == "BELONGS_TO"
    graph = (await client.get("/api/v1/knowledge/graph", headers=auth_headers)).json()["data"]
    assert len(graph["entities"]) == 2
    assert len(graph["relations"]) == 1
    assert (await client.get("/api/v1/knowledge/tags", headers=auth_headers)).status_code == 200
    assert (await client.get("/api/v1/knowledge/categories", headers=auth_headers)).status_code == 200

    assert len((await client.get("/api/v1/workflows", headers=auth_headers)).json()["data"]) == 1
    assert repository.json()["data"]["status"] == "ready"
