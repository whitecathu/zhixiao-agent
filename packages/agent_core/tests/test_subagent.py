from pathlib import Path

import pytest

from zhixiao_agent.model import ModelTurn, ScriptedModel
from zhixiao_agent.subagent import build_sub_agent_handler, run_sub_agent
from zhixiao_agent.tools.base import BaseTool, ToolContext
from zhixiao_agent.tools.filesystem import WriteFileTool
from zhixiao_agent.tools.integrations import SubAgentTool
from zhixiao_agent.tools.registry import ToolRegistry, build_default_registry
from zhixiao_agent.types import PermissionMode, ToolCall, ToolResult, ToolStatus


class ContextProbeTool(BaseTool):
    name = "read_file"
    description = "Capture the effective child security context."

    def __init__(self, seen: list[tuple[PermissionMode, bool, bool]]) -> None:
        self.seen = seen

    async def execute(
        self,
        arguments: dict,
        context: ToolContext,
    ) -> ToolResult:
        self.seen.append(
            (context.permission, context.ops_approved, context.network_approved)
        )
        return ToolResult.ok("captured context")


@pytest.mark.asyncio
async def test_sub_agent_completes_readonly_task(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hello from workspace\n", encoding="utf-8")
    model = ScriptedModel(
        [
            ModelTurn(
                tool_calls=[ToolCall(id="1", name="read_file", arguments={"path": "README.md"})]
            ),
            ModelTurn(content="README says hello from workspace."),
        ]
    )
    events: list[dict] = []

    async def on_event(event: dict) -> None:
        events.append(event)

    result = await run_sub_agent(
        "Read README and summarize it",
        model=model,
        workspace=tmp_path,
        permission=PermissionMode.READ_ONLY,
        ops_approved=True,
        network_approved=False,
        parent_run_id="parent-1",
        on_event=on_event,
    )

    assert result["status"] == "ok"
    assert "hello from workspace" in result["summary"]
    assert result["parent_run"] == "parent-1"
    assert result["sub_agent_depth"] == 1
    assert any(item["tool"] == "read_file" for item in result["tools"])
    assert events
    assert all(event.get("sub_agent") is True for event in events)
    assert all(event.get("parent_run") == "parent-1" for event in events)
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert len({event["run_id"] for event in events}) == 1


@pytest.mark.asyncio
async def test_sub_agent_nesting_beyond_depth_one_is_blocked(tmp_path: Path) -> None:
    model = ScriptedModel([ModelTurn(content="should not run")])
    result = await run_sub_agent(
        "Nested delegation must fail",
        model=model,
        workspace=tmp_path,
        permission=PermissionMode.READ_ONLY,
        ops_approved=True,
        network_approved=False,
        metadata={"sub_agent_depth": 1},
        parent_run_id="parent-2",
    )
    assert result["status"] == "blocked"
    assert "nesting" in result["summary"]
    assert model.messages == []


@pytest.mark.asyncio
async def test_build_sub_agent_handler_wires_sub_agent_tool(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("payload\n", encoding="utf-8")
    model = ScriptedModel(
        [
            ModelTurn(
                tool_calls=[ToolCall(id="1", name="read_file", arguments={"path": "note.txt"})]
            ),
            ModelTurn(content="Found payload."),
        ]
    )
    handler = build_sub_agent_handler(
        model,
        lambda: tmp_path,
        permission=PermissionMode.READ_ONLY,
        ops_approved=True,
        parent_run_id="run-42",
    )
    from zhixiao_agent.runner import LocalRunner
    from zhixiao_agent.tools.base import ToolContext

    context = ToolContext(
        workspace=tmp_path,
        permission=PermissionMode.FULL,
        runner=LocalRunner(tmp_path),
        approved=True,
        ops_approved=True,
        ops_capabilities=frozenset({"sub_agent"}),
        metadata={"sub_agent": handler, "sub_agent_depth": 0},
    )
    delegated = await SubAgentTool().execute({"task": "Read note.txt and report"}, context)
    assert delegated.status is ToolStatus.SUCCESS
    assert delegated.data["status"] == "ok"
    assert "payload" in delegated.data["summary"]
    assert delegated.data["parent_run"] == "run-42"


@pytest.mark.asyncio
async def test_handler_blocks_when_parent_is_already_a_sub_agent(tmp_path: Path) -> None:
    model = ScriptedModel([ModelTurn(content="nope")])
    handler = build_sub_agent_handler(
        model,
        lambda: tmp_path,
        permission=PermissionMode.READ_ONLY,
        ops_approved=True,
        parent_depth=1,
    )
    result = await handler("try nested")
    assert result["status"] == "blocked"


@pytest.mark.asyncio
async def test_handler_enforces_fixed_readonly_child_capabilities(tmp_path: Path) -> None:
    seen: list[tuple[PermissionMode, bool, bool]] = []
    model = ScriptedModel(
        [
            ModelTurn(
                tool_calls=[
                    ToolCall(
                        id="write-1",
                        name="write_file",
                        arguments={"path": "unsafe.txt", "content": "unsafe"},
                    ),
                    ToolCall(id="probe-1", name="read_file", arguments={}),
                ]
            ),
            ModelTurn(content="checked"),
        ]
    )
    registry = ToolRegistry([WriteFileTool(), ContextProbeTool(seen)])
    handler = build_sub_agent_handler(
        model,
        lambda: tmp_path,
        permission=PermissionMode.FULL,
        approved=True,
        ops_approved=True,
        network_approved=True,
        tool_allowlist={"read_file", "write_file", "sub_agent"},
        registry=registry,
    )

    result = await handler("Attempt a dangerous write and inspect context")

    assert result["status"] == "error"
    assert not (tmp_path / "unsafe.txt").exists()
    assert seen == [(PermissionMode.READ_ONLY, False, False)]
    assert [item["tool"] for item in result["tools"]] == ["write_file", "read_file"]


def test_registry_exposes_sub_agent_when_experimental() -> None:
    registry = build_default_registry(include_experimental=True)
    assert registry.get("sub_agent") is not None
    plain = ToolRegistry([])
    assert plain.get("sub_agent") is None
