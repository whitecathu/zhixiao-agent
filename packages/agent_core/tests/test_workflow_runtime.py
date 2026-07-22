from pathlib import Path

import pytest
from pydantic import ValidationError

from zhixiao_agent.model import ModelTurn, ScriptedModel
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
