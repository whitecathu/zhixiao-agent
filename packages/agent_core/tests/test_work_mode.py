from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from zhixiao_agent.model import ModelTurn, ScriptedModel
from zhixiao_agent.runtime import AgentRuntime, RuntimeConfig
from zhixiao_agent.tools.registry import READ_ONLY_TOOLS
from zhixiao_agent.types import PermissionMode, RunStatus, ToolCall, ToolStatus

_WRITE_TOOLS = frozenset(
    {"write_file", "exact_edit", "terminal", "run_tests", "background_command"}
)


class RecordingModel(ScriptedModel):
    def __init__(self, turns: list[ModelTurn]) -> None:
        super().__init__(turns)
        self.advertised: list[set[str]] = []

    async def complete(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelTurn:
        if tools is not None:
            names = {
                str(item.get("function", {}).get("name") or "")
                for item in tools
                if isinstance(item, dict)
            }
            self.advertised.append({name for name in names if name})
        return await super().complete(messages, tools=tools)


def _feature_turns(*, write: bool = False) -> list[ModelTurn]:
    execute_turn = ModelTurn(content="Inspection complete.")
    if write:
        execute_turn = ModelTurn(
            tool_calls=[
                ToolCall(
                    id="write",
                    name="write_file",
                    arguments={"path": "feature.txt", "content": "done\n"},
                )
            ]
        )
    return [
        ModelTurn(content='{"plan":["Inspect then implement"]}'),
        execute_turn,
        ModelTurn(content="Inspection complete."),
    ]


def test_runtime_config_accepts_mode_kwarg() -> None:
    assert RuntimeConfig().mode == "code"
    assert RuntimeConfig(mode="ask").mode == "ask"


@pytest.mark.asyncio
async def test_ask_mode_rejects_write_tools_even_with_edit_permission(tmp_path: Path) -> None:
    model = RecordingModel(_feature_turns(write=True))
    result = await AgentRuntime(model).run(
        "implement a feature",
        tmp_path,
        RuntimeConfig(
            permission=PermissionMode.EDIT,
            require_plan_approval=False,
            isolate_worktree=False,
            mode="ask",
            allow_unverified="ask mode must not mutate the workspace",
        ),
    )

    assert result.status is RunStatus.SUCCEEDED
    assert model.advertised
    advertised = set.union(*model.advertised)
    assert advertised <= READ_ONLY_TOOLS
    assert advertised.isdisjoint(_WRITE_TOOLS)
    write_events = [
        event
        for event in result.events
        if event.event == "tool_result" and event.data.get("tool") == "write_file"
    ]
    assert write_events
    assert write_events[0].data["status"] == ToolStatus.ERROR.value
    assert write_events[0].data["result"]["root_cause"] == "write_file"
    assert not (tmp_path / "feature.txt").exists()


@pytest.mark.asyncio
async def test_review_mode_intersects_allowed_tools_with_read_only(tmp_path: Path) -> None:
    model = RecordingModel(_feature_turns())
    result = await AgentRuntime(model).run(
        "implement a feature",
        tmp_path,
        RuntimeConfig(
            permission=PermissionMode.FULL,
            require_plan_approval=False,
            isolate_worktree=False,
            mode="review",
            allow_unverified="review mode does not mutate",
        ),
    )

    assert result.status is RunStatus.SUCCEEDED
    assert model.advertised
    advertised = set.union(*model.advertised)
    assert advertised <= READ_ONLY_TOOLS
    assert advertised.isdisjoint(_WRITE_TOOLS)


@pytest.mark.asyncio
async def test_plan_mode_forces_plan_approval_when_not_read_only(tmp_path: Path) -> None:
    model = RecordingModel([ModelTurn(content='{"plan":["Inspect then implement"]}')])
    result = await AgentRuntime(model).run(
        "implement a feature",
        tmp_path,
        RuntimeConfig(
            permission=PermissionMode.EDIT,
            require_plan_approval=False,
            isolate_worktree=False,
            mode="plan",
        ),
    )

    assert result.status is RunStatus.AWAITING_APPROVAL
    assert any(event.event == "approval_required" for event in result.events)
    assert model.advertised == []


@pytest.mark.asyncio
async def test_plan_mode_read_only_continues_without_approval(tmp_path: Path) -> None:
    model = RecordingModel(_feature_turns())
    result = await AgentRuntime(model).run(
        "implement a feature",
        tmp_path,
        RuntimeConfig(
            permission=PermissionMode.READ_ONLY,
            require_plan_approval=False,
            mode="plan",
        ),
    )

    assert result.status is RunStatus.SUCCEEDED
    assert model.advertised
    advertised = set.union(*model.advertised)
    assert advertised <= READ_ONLY_TOOLS


@pytest.mark.asyncio
async def test_code_mode_keeps_write_tools_for_feature_tasks(tmp_path: Path) -> None:
    model = RecordingModel(_feature_turns(write=True))
    result = await AgentRuntime(model).run(
        "implement a feature",
        tmp_path,
        RuntimeConfig(
            permission=PermissionMode.EDIT,
            require_plan_approval=False,
            isolate_worktree=False,
            mode="code",
            allow_unverified="fixture intentionally has no test runner",
        ),
    )

    assert result.status is RunStatus.SUCCEEDED
    assert model.advertised
    advertised = set.union(*model.advertised)
    assert "write_file" in advertised
    assert (tmp_path / "feature.txt").read_text(encoding="utf-8") == "done\n"


@pytest.mark.asyncio
async def test_command_tools_intersect_allowed_set(tmp_path: Path) -> None:
    model = RecordingModel(_feature_turns())
    result = await AgentRuntime(model).run(
        "inspect only",
        tmp_path,
        RuntimeConfig(
            permission=PermissionMode.FULL,
            require_plan_approval=False,
            isolate_worktree=False,
            mode="code",
            tool_metadata={"command_tools": ["read_file", "grep"]},
            allow_unverified="custom command tool allowlist",
        ),
    )

    assert result.status is RunStatus.SUCCEEDED
    assert model.advertised
    advertised = set.union(*model.advertised)
    assert advertised <= {"read_file", "grep"}


@pytest.mark.asyncio
async def test_tool_metadata_mode_is_honored_when_config_mode_is_default(tmp_path: Path) -> None:
    model = RecordingModel(_feature_turns(write=True))
    result = await AgentRuntime(model).run(
        "implement a feature",
        tmp_path,
        RuntimeConfig(
            permission=PermissionMode.FULL,
            require_plan_approval=False,
            isolate_worktree=False,
            tool_metadata={"mode": "ask"},
            allow_unverified="ask mode must not mutate the workspace",
        ),
    )

    assert result.status is RunStatus.SUCCEEDED
    assert model.advertised
    advertised = set.union(*model.advertised)
    assert advertised <= READ_ONLY_TOOLS
    write_events = [
        event
        for event in result.events
        if event.event == "tool_result" and event.data.get("tool") == "write_file"
    ]
    assert write_events
    assert write_events[0].data["status"] == ToolStatus.ERROR.value
    assert not (tmp_path / "feature.txt").exists()
