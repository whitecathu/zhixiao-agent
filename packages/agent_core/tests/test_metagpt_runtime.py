"""MetaGPT Team runtime vertical slice."""

from pathlib import Path
from typing import Any

import pytest

from zhixiao_agent.metagpt import Message
from zhixiao_agent.metagpt_runtime import run_metagpt_team
from zhixiao_agent.model import ScriptedModel
from zhixiao_agent.tools.base import BaseTool, ToolContext
from zhixiao_agent.tools.registry import ToolRegistry
from zhixiao_agent.types import ModelTurn, PermissionMode, RunStatus, ToolCall, ToolResult


class RecordingTool(BaseTool):
    name = "metadata_probe"
    description = "Record tool context metadata for tests."

    def __init__(self, seen: list[dict[str, Any]]) -> None:
        self.seen = seen

    async def execute(
        self,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        self.seen.append(dict(context.metadata))
        return ToolResult.ok("metadata recorded")


class DangerousTool(BaseTool):
    name = "write_file"
    description = "A dangerous marker tool that must never run."

    def __init__(self, calls: list[dict[str, Any]]) -> None:
        self.calls = calls

    async def execute(
        self,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        self.calls.append(arguments)
        return ToolResult.ok("dangerous tool ran")


class FailingModel(ScriptedModel):
    async def complete(
        self,
        messages: Any,
        *,
        tools: Any = None,
    ) -> ModelTurn:
        raise RuntimeError("model unavailable")


@pytest.mark.asyncio
async def test_metagpt_team_emits_compatible_events(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    model = ScriptedModel(
        [
            ModelTurn(
                content="",
                model="scripted",
                tool_calls=[
                    ToolCall(id="1", name="list_directory", arguments={"path": ".", "limit": 20})
                ],
            ),
            ModelTurn(content="Listed the workspace root.", model="scripted"),
        ]
    )
    events: list[dict] = []

    async def on_event(event: dict) -> None:
        events.append(event)

    result = await run_metagpt_team(
        "List the workspace files",
        tmp_path,
        model=model,
        permission=PermissionMode.READ_ONLY,
        approved=True,
        run_id="mg-1",
        on_event=on_event,
        roles_json='[{"name":"explorer","profile":"explorer","tools":["list_directory","read_file"],"watch":[]}]',
        max_iterations=3,
    )
    assert result.status is RunStatus.SUCCEEDED
    assert any(item["event"] == "run_started" for item in events)
    assert any(item["event"] == "workflow_node_started" for item in events)
    assert any(item["event"] == "tool_result" for item in events)
    assert any(item["event"] == "run_finished" for item in events)
    assert [item["sequence"] for item in events] == list(range(1, len(events) + 1))
    assert len(model.messages) == 2
    assert [message["role"] for message in model.messages[1][-2:]] == ["assistant", "tool"]


@pytest.mark.asyncio
async def test_metagpt_schedules_multiple_unwatched_roles_fairly(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            ModelTurn(content="first done"),
            ModelTurn(content="second done"),
            ModelTurn(content="third done"),
        ]
    )
    result = await run_metagpt_team(
        "Inspect the workspace",
        tmp_path,
        model=model,
        roles_json=(
            '[{"name":"first","watch":[]},{"name":"second","watch":[]},'
            '{"name":"third","watch":[]}]'
        ),
        max_iterations=3,
    )

    assert result.status is RunStatus.SUCCEEDED
    assert result.plan == [
        "MetaGPT role: first",
        "MetaGPT role: second",
        "MetaGPT role: third",
    ]
    started = [
        event.data["node_id"]
        for event in result.events
        if event.event == "workflow_node_started"
    ]
    assert started == ["first", "second", "third"]


@pytest.mark.asyncio
async def test_metagpt_propagates_metadata_to_tool_context(tmp_path: Path) -> None:
    seen: list[dict[str, Any]] = []
    model = ScriptedModel(
        [
            ModelTurn(
                tool_calls=[ToolCall(id="probe-1", name="metadata_probe", arguments={})]
            ),
            ModelTurn(content="metadata checked"),
        ]
    )
    result = await run_metagpt_team(
        "Check metadata",
        tmp_path,
        model=model,
        registry=ToolRegistry([RecordingTool(seen)]),
        roles_json='[{"name":"probe","tools":["metadata_probe"],"watch":[]}]',
        tool_metadata={"trace_id": "trace-123"},
        max_tool_iterations=2,
    )

    assert result.status is RunStatus.SUCCEEDED
    assert seen == [{"trace_id": "trace-123"}]


@pytest.mark.asyncio
async def test_empty_metagpt_role_tools_never_expand_to_registry(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    model = ScriptedModel(
        [
            ModelTurn(
                tool_calls=[
                    ToolCall(
                        id="danger-1",
                        name="write_file",
                        arguments={"path": "owned.txt", "content": "unsafe"},
                    )
                ]
            ),
            ModelTurn(content="done"),
        ]
    )
    result = await run_metagpt_team(
        "Do not mutate files",
        tmp_path,
        model=model,
        permission=PermissionMode.FULL,
        approved=True,
        registry=ToolRegistry([DangerousTool(calls)]),
        roles_json='[{"name":"empty","tools":[],"watch":[]}]',
        max_tool_iterations=2,
    )

    assert result.status is RunStatus.FAILED
    assert calls == []
    assert not (tmp_path / "owned.txt").exists()


def test_metagpt_messages_use_timezone_aware_timestamps() -> None:
    assert Message(content="hello").created_at.utcoffset() is not None


@pytest.mark.asyncio
async def test_metagpt_model_failure_returns_compatible_failed_result(tmp_path: Path) -> None:
    result = await run_metagpt_team(
        "Inspect the workspace",
        tmp_path,
        model=FailingModel([]),
        roles_json='[{"name":"failing","watch":[]}]',
    )

    assert result.status is RunStatus.FAILED
    assert result.error == "one or more roles failed"
    assert [event.event for event in result.events][-3:] == [
        "model_turn",
        "workflow_node_finished",
        "run_finished",
    ]
    assert result.events[-3].data["failed"] is True


@pytest.mark.asyncio
async def test_metagpt_write_mode_requires_verification_or_waiver(tmp_path: Path) -> None:
    model = ScriptedModel([ModelTurn(content="must not run")])
    result = await run_metagpt_team(
        "Implement a file",
        tmp_path,
        model=model,
        permission=PermissionMode.EDIT,
        roles_json='[{"name":"implementer","tools":["write_file"],"watch":[]}]',
    )

    assert result.status is RunStatus.FAILED
    assert result.verification.outcome.value == "blocked"
    assert result.termination_reason.value == "verification_blocked"
    assert model.messages == []
