import asyncio
import json
from pathlib import Path

import pytest

from zhixiao_agent.runner import LocalRunner
from zhixiao_agent.tools.base import ToolContext
from zhixiao_agent.tools.integrations import (
    BackgroundCommandTool,
    KnowledgeSearchTool,
    MCPTool,
    SubAgentTool,
    WebSearchTool,
)
from zhixiao_agent.types import PermissionMode, ToolStatus


def context(tmp_path: Path, *, full: bool = False) -> ToolContext:
    return ToolContext(
        workspace=tmp_path,
        permission=PermissionMode.FULL if full else PermissionMode.READ_ONLY,
        runner=LocalRunner(tmp_path),
        approved=full,
    )


@pytest.mark.asyncio
async def test_knowledge_search_returns_ranked_records(tmp_path: Path) -> None:
    directory = tmp_path / ".zhixiao"
    directory.mkdir()
    (directory / "knowledge.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"text": "FastAPI endpoint contract"}),
                json.dumps({"text": "Vue component"}),
            ]
        ),
        encoding="utf-8",
    )
    result = await KnowledgeSearchTool().execute({"query": "FastAPI contract"}, context(tmp_path))
    assert result.status is ToolStatus.SUCCESS
    assert result.data == [{"text": "FastAPI endpoint contract"}]


@pytest.mark.asyncio
async def test_network_and_delegation_require_explicit_approval(tmp_path: Path) -> None:
    restricted = context(tmp_path)
    web = await WebSearchTool().execute({"query": "LangGraph persistence"}, restricted)
    delegated = await SubAgentTool().execute({"task": "Inspect the API contract"}, restricted)
    assert web.status is ToolStatus.BLOCKED
    assert delegated.status is ToolStatus.BLOCKED


@pytest.mark.asyncio
async def test_subagent_and_mcp_use_audited_adapters(tmp_path: Path) -> None:
    full = context(tmp_path, full=True).model_copy(
        update={
            "metadata": {
                "sub_agent": lambda task: {"task": task, "status": "done"},
                "mcp": lambda server, tool, arguments: {
                    "server": server,
                    "tool": tool,
                    **arguments,
                },
                "mcp_whitelist": ["local:read"],
            }
        }
    )
    delegated = await SubAgentTool().execute({"task": "Inspect the API contract"}, full)
    mcp = await MCPTool().execute(
        {"server": "local", "tool": "read", "arguments": {"path": "README.md"}}, full
    )
    assert delegated.status is ToolStatus.SUCCESS
    assert mcp.status is ToolStatus.SUCCESS


@pytest.mark.asyncio
async def test_background_command_can_be_observed(tmp_path: Path) -> None:
    full = context(tmp_path, full=True)
    tool = BackgroundCommandTool()
    started = await tool.execute(
        {"action": "start", "command": "python -c print(42)", "timeout": 10}, full
    )
    # Process startup on shared CI runners can exceed a fixed sleep. Poll the public
    # status contract so the test verifies completion without introducing a race.
    for _ in range(50):
        status = await tool.execute({"action": "status", "job_id": started.data["job_id"]}, full)
        if status.data.get("state") != "running":
            break
        await asyncio.sleep(0.1)
    else:
        pytest.fail("background command did not finish within 5 seconds")
    assert status.status is ToolStatus.SUCCESS
    assert status.data["exit_code"] == 0
