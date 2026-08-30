from pathlib import Path

import pytest
from pydantic import ValidationError

from zhixiao_agent.model import ModelTurn, ScriptedModel
from zhixiao_agent.runner import LocalRunner
from zhixiao_agent.runtime import AgentRuntime, RuntimeConfig
from zhixiao_agent.types import PermissionMode, RunStatus, ToolCall
from zhixiao_agent.workflow import WorkflowDefinition


def test_workflow_definition_rejects_cycles_and_unreachable_nodes() -> None:
    with pytest.raises(ValidationError, match="cycles"):
        WorkflowDefinition.model_validate(
            {
                "nodes": [
                    {"id": "one", "role": "planner"},
                    {"id": "two", "role": "tester"},
                ],
                "edges": [
                    {"source": "one", "target": "two"},
                    {"source": "two", "target": "one"},
                ],
            }
        )
    with pytest.raises(ValidationError, match="reachable"):
        WorkflowDefinition.model_validate(
            {
                "nodes": [
                    {"id": "one", "role": "planner"},
                    {"id": "orphan", "role": "tester"},
                ],
                "edges": [],
            }
        )


@pytest.mark.asyncio
async def test_runtime_executes_bound_workflow_nodes_in_dsl_order(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("workflow\n", encoding="utf-8")
    workflow = {
        "entrypoint": "explore",
        "nodes": [
            {"id": "explore", "role": "explorer"},
            {"id": "plan", "role": "planner"},
            {
                "id": "implement",
                "role": "implementer",
                "tool_allowlist": ["read_file"],
            },
            {"id": "test", "role": "tester"},
        ],
        "edges": [
            {"source": "explore", "target": "plan"},
            {"source": "plan", "target": "implement"},
            {"source": "implement", "target": "test", "condition": "success"},
        ],
    }
    model = ScriptedModel(
        [
            ModelTurn(content='{"plan":["Inspect README","Verify"]}'),
            ModelTurn(
                tool_calls=[ToolCall(id="read", name="read_file", arguments={"path": "README.md"})]
            ),
            ModelTurn(content="Workflow implementation completed."),
        ]
    )
    result = await AgentRuntime(model).run(
        "implement workflow support",
        tmp_path,
        RuntimeConfig(
            permission=PermissionMode.READ_ONLY,
            require_plan_approval=False,
            workflow_definition=workflow,
            workflow_version=7,
        ),
    )

    assert result.status is RunStatus.SUCCEEDED
    started = [
        event.data["node_id"]
        for event in result.events
        if event.event == "workflow_node_started"
    ]
    assert started == ["explore", "plan", "implement", "test"]
    assert next(event for event in result.events if event.event == "run_started").data[
        "workflow_version"
    ] == 7
    assert any(event.event == "tool_result" for event in result.events)


@pytest.mark.asyncio
async def test_runtime_retries_failed_workflow_node(tmp_path: Path) -> None:
    workflow = {
        "nodes": [
            {
                "id": "implement",
                "role": "implementer",
                "tool_allowlist": ["read_file"],
                "retries": 1,
            }
        ],
        "edges": [],
    }
    model = ScriptedModel(
        [
            ModelTurn(
                tool_calls=[
                    ToolCall(id="missing", name="read_file", arguments={"path": "missing.txt"})
                ]
            ),
            ModelTurn(content="Recovered after inspecting the tool error."),
        ]
    )
    result = await AgentRuntime(model).run(
        "implement retry behavior",
        tmp_path,
        RuntimeConfig(
            permission=PermissionMode.READ_ONLY,
            require_plan_approval=False,
            max_tool_iterations=1,
            workflow_definition=workflow,
        ),
    )

    assert result.status is RunStatus.SUCCEEDED
    assert any(event.event == "workflow_node_retry" for event in result.events)
    assert result.summary == "Recovered after inspecting the tool error."


@pytest.mark.asyncio
async def test_each_workflow_node_requires_its_own_approval(tmp_path: Path) -> None:
    workflow = {
        "entrypoint": "first",
        "nodes": [
            {"id": "first", "role": "reviewer", "approval_required": True},
            {"id": "second", "role": "reviewer", "approval_required": True},
        ],
        "edges": [{"source": "first", "target": "second"}],
    }
    config = RuntimeConfig(
        permission=PermissionMode.READ_ONLY,
        require_plan_approval=False,
        workflow_definition=workflow,
    )
    runtime = AgentRuntime(
        ScriptedModel([ModelTurn(content="first done"), ModelTurn(content="second done")])
    )

    first = await runtime.run("review the project", tmp_path, config, run_id="node-approval")
    second = await runtime.resume("node-approval", approved=True, config=config)
    completed = await runtime.resume("node-approval", approved=True, config=config)

    assert first.status is RunStatus.AWAITING_APPROVAL
    assert second.status is RunStatus.AWAITING_APPROVAL
    approvals = [
        next(
            event.data["approval_id"]
            for event in reversed(result.events)
            if event.event == "approval_required"
        )
        for result in (first, second)
    ]
    assert approvals == [
        "node-approval:workflow:first",
        "node-approval:workflow:second",
    ]
    assert completed.status is RunStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_workflow_approvals_happen_before_worktree_creation(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "README.md").write_text("workflow approvals\n", encoding="utf-8")
    runner = LocalRunner(repository)
    for command in (
        "git init -b main",
        "git -c user.name=Test -c user.email=test@example.com add .",
        "git -c user.name=Test -c user.email=test@example.com commit -m init",
    ):
        command_result = await runner.run(command, permission=PermissionMode.EXECUTE)
        assert command_result.exit_code == 0, command_result.stderr

    workflow = {
        "entrypoint": "first",
        "nodes": [
            {"id": "first", "role": "reviewer", "approval_required": True},
            {"id": "second", "role": "reviewer", "approval_required": True},
        ],
        "edges": [{"source": "first", "target": "second"}],
    }
    config = RuntimeConfig(
        permission=PermissionMode.EDIT,
        require_plan_approval=False,
        workflow_definition=workflow,
        allow_unverified="approval ordering fixture has no verification command",
    )
    runtime = AgentRuntime(
        ScriptedModel([ModelTurn(content="first done"), ModelTurn(content="second done")])
    )
    worktree_root = repository.parent / ".zhixiao-worktrees" / repository.name

    first = await runtime.run(
        "review the project",
        repository,
        config,
        run_id="workflow-before-worktree",
    )
    assert first.status is RunStatus.AWAITING_APPROVAL
    assert not worktree_root.exists()

    second = await runtime.resume("workflow-before-worktree", approved=True, config=config)
    assert second.status is RunStatus.AWAITING_APPROVAL
    assert not worktree_root.exists()

    completed = await runtime.resume("workflow-before-worktree", approved=True, config=config)
    assert completed.status is RunStatus.SUCCEEDED
    assert (worktree_root / "workflow-before-worktree").is_dir()
