import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from zhixiao_agent.runner import CommandResult, LocalRunner, Runner
from zhixiao_agent.tools import integrations
from zhixiao_agent.tools.base import ToolContext
from zhixiao_agent.tools.integrations import (
    BackgroundCommandTool,
    KnowledgeSearchTool,
    MCPTool,
    OpenPullRequestTool,
    SubAgentTool,
    WebFetchTool,
    WebSearchTool,
)
from zhixiao_agent.tools.registry import build_default_registry
from zhixiao_agent.types import PermissionMode, ToolStatus


def context(
    tmp_path: Path,
    *,
    full: bool = False,
    network: bool = False,
    ops: bool = False,
) -> ToolContext:
    return ToolContext(
        workspace=tmp_path,
        permission=PermissionMode.FULL if full else PermissionMode.READ_ONLY,
        runner=LocalRunner(tmp_path),
        approved=full,
        network_approved=network or full,
        # full unlocks web fetch/search for SSRF tests; scoped ops stay empty unless
        # a test opts into ops=True without auto-granting git_publish/mcp/sub_agent.
        network_capabilities=frozenset({"web"}) if (network or full) else frozenset(),
        ops_approved=ops or full,
        ops_capabilities=frozenset(),
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
    assert result.data["degraded"] is False
    assert result.data["hits"][0]["record"] == {"text": "FastAPI endpoint contract"}


@pytest.mark.asyncio
async def test_network_and_delegation_require_explicit_approval(tmp_path: Path) -> None:
    restricted = context(tmp_path)
    web = await WebSearchTool().execute({"query": "LangGraph persistence"}, restricted)
    delegated = await SubAgentTool().execute({"task": "Inspect the API contract"}, restricted)
    assert web.status is ToolStatus.BLOCKED
    assert delegated.status is ToolStatus.BLOCKED


@pytest.mark.asyncio
async def test_plan_approval_does_not_unlock_network_or_ops(tmp_path: Path) -> None:
    plan_only = ToolContext(
        workspace=tmp_path,
        permission=PermissionMode.FULL,
        runner=LocalRunner(tmp_path),
        approved=True,
        network_approved=False,
        ops_approved=False,
    )
    web = await WebSearchTool().execute({"query": "LangGraph persistence"}, plan_only)
    delegated = await SubAgentTool().execute({"task": "Inspect the API contract"}, plan_only)
    assert web.status is ToolStatus.BLOCKED
    assert delegated.status is ToolStatus.BLOCKED


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["http://127.0.0.1/admin", "http://localhost/admin"])
async def test_web_fetch_blocks_localhost_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    url: str,
) -> None:
    calls: list[str] = []

    class FakeClient:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def get(self, requested_url: str) -> httpx.Response:
            calls.append(requested_url)
            raise AssertionError("unsafe URL must not be requested")

    monkeypatch.setattr(integrations, "_resolve_host_addresses", lambda *_args: {"127.0.0.1"})
    monkeypatch.setattr(integrations.httpx, "AsyncClient", FakeClient)

    result = await WebFetchTool().execute({"url": url}, context(tmp_path, full=True))
    assert result.status is ToolStatus.BLOCKED
    assert "non-public address" in (result.root_cause or "")
    assert calls == []


@pytest.mark.asyncio
async def test_web_fetch_blocks_userinfo_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def get(self, _url: str) -> httpx.Response:
            raise AssertionError("URL with credentials must not be requested")

    monkeypatch.setattr(integrations.httpx, "AsyncClient", FakeClient)
    result = await WebFetchTool().execute(
        {"url": "https://user:secret@example.com/resource"},
        context(tmp_path, full=True),
    )
    assert result.status is ToolStatus.BLOCKED
    assert "user information" in (result.root_cause or "")


@pytest.mark.asyncio
async def test_web_fetch_validates_redirect_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    redirect = httpx.Response(
        302,
        headers={"location": "http://internal.test/admin"},
        request=httpx.Request("GET", "https://public.test/start"),
    )

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            assert kwargs["follow_redirects"] is False

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def get(self, requested_url: str) -> httpx.Response:
            calls.append(requested_url)
            return redirect

    def resolve(host: str, _port: int) -> set[str]:
        return {"8.8.8.8"} if host == "public.test" else {"10.0.0.4"}

    monkeypatch.setattr(integrations, "_resolve_host_addresses", resolve)
    monkeypatch.setattr(integrations.httpx, "AsyncClient", FakeClient)

    result = await WebFetchTool().execute(
        {"url": "https://public.test/start"},
        context(tmp_path, full=True),
    )
    assert result.status is ToolStatus.BLOCKED
    assert "internal.test" in (result.root_cause or "")
    assert calls == ["https://public.test/start"]


@pytest.mark.asyncio
async def test_subagent_and_mcp_use_audited_adapters(tmp_path: Path) -> None:
    full = context(tmp_path, full=True).model_copy(
        update={
            "ops_capabilities": frozenset({"mcp", "sub_agent"}),
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


def _mcp_context(
    tmp_path: Path,
    *,
    transports: dict[str, str] | None,
    network_approved: bool | None,
) -> ToolContext:
    metadata: dict[str, Any] = {
        "mcp": lambda server, tool, arguments: {
            "server": server,
            "tool": tool,
            **arguments,
        },
        "mcp_whitelist": ["local:read", "docs:search"],
    }
    if transports is not None:
        metadata["mcp_server_transports"] = transports
    if network_approved is not None:
        metadata["mcp_network_approved"] = network_approved
    return context(tmp_path, full=True).model_copy(
        update={
            "ops_capabilities": frozenset({"mcp"}),
            "metadata": metadata,
        }
    )


@pytest.mark.asyncio
async def test_mcp_stdio_succeeds_without_network_approval(tmp_path: Path) -> None:
    result = await MCPTool().execute(
        {"server": "local", "tool": "read", "arguments": {"path": "README.md"}},
        _mcp_context(
            tmp_path,
            transports={"local": "stdio", "docs": "http"},
            network_approved=False,
        ),
    )
    assert result.status is ToolStatus.SUCCESS
    assert result.data["server"] == "local"


@pytest.mark.asyncio
async def test_mcp_http_blocked_without_network_approval(tmp_path: Path) -> None:
    result = await MCPTool().execute(
        {"server": "docs", "tool": "search", "arguments": {"q": "agent"}},
        _mcp_context(
            tmp_path,
            transports={"local": "stdio", "docs": "http"},
            network_approved=False,
        ),
    )
    assert result.status is ToolStatus.BLOCKED
    assert "network" in (result.root_cause or "").lower()


@pytest.mark.asyncio
async def test_mcp_unknown_transport_blocked_without_network_approval(tmp_path: Path) -> None:
    result = await MCPTool().execute(
        {"server": "local", "tool": "read", "arguments": {"path": "README.md"}},
        _mcp_context(tmp_path, transports={}, network_approved=False),
    )
    assert result.status is ToolStatus.BLOCKED
    assert "network" in (result.root_cause or "").lower()


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


@pytest.mark.asyncio
async def test_open_pull_request_blocked_without_publish_capability(tmp_path: Path) -> None:
    restricted = context(tmp_path)
    plan_only = ToolContext(
        workspace=tmp_path,
        permission=PermissionMode.FULL,
        runner=LocalRunner(tmp_path),
        approved=True,
        network_approved=True,
        ops_approved=False,
    )
    tool = OpenPullRequestTool()
    blocked = await tool.execute({"title": "Ship feature X"}, restricted)
    still_blocked = await tool.execute({"title": "Ship feature X"}, plan_only)
    assert blocked.status is ToolStatus.BLOCKED
    assert still_blocked.status is ToolStatus.BLOCKED
    assert "git_publish" in (still_blocked.root_cause or "")


@pytest.mark.asyncio
async def test_open_pull_request_requires_dedicated_publish_capability(tmp_path: Path) -> None:
    called = False

    def open_pr(*_args: Any) -> dict[str, str]:
        nonlocal called
        called = True
        return {"url": "https://example.test/pr/1"}

    generic_ops_only = context(tmp_path, full=True, ops=True).model_copy(
        update={"metadata": {"open_pr": open_pr}}
    )
    result = await OpenPullRequestTool().execute(
        {"title": "Ship feature X"},
        generic_ops_only,
    )
    assert result.status is ToolStatus.BLOCKED
    assert "git_publish" in (result.root_cause or "")
    assert called is False


@pytest.mark.asyncio
async def test_open_pull_request_uses_metadata_callback(tmp_path: Path) -> None:
    full = context(tmp_path, full=True, ops=True, network=True).model_copy(
        update={
            "network_approved": False,
            "network_capabilities": frozenset(),
            "ops_capabilities": frozenset({"git_publish"}),
            "metadata": {
                "ops_capabilities": ["git_publish"],
                "open_pr": lambda title, body, base, head, draft: {
                    "url": "https://example.test/pr/1",
                    "title": title,
                    "base": base,
                    "head": head,
                    "draft": draft,
                    "body": body,
                }
            }
        }
    )
    result = await OpenPullRequestTool().execute(
        {"title": "Add workspace index", "body": "P2", "base": "main", "draft": True},
        full,
    )
    assert result.status is ToolStatus.SUCCESS
    assert result.data["url"].endswith("/pr/1")
    assert result.data["draft"] is True


@pytest.mark.asyncio
async def test_open_pull_request_gh_fallback_requires_network_and_passes_capability(
    tmp_path: Path,
) -> None:
    class RecordingRunner(Runner):
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def run(
            self,
            command: str,
            *,
            permission: PermissionMode,
            timeout: int = 120,
            approved: bool = False,
        ) -> CommandResult:
            self.calls.append(
                {
                    "command": command,
                    "permission": permission,
                    "timeout": timeout,
                    "approved": approved,
                }
            )
            return CommandResult(
                command=command,
                exit_code=0,
                stdout="https://github.test/org/repo/pull/1",
                stderr="",
            )

    runner = RecordingRunner()
    base = ToolContext(
        workspace=tmp_path,
        permission=PermissionMode.FULL,
        runner=runner,
        approved=True,
        ops_approved=True,
        ops_capabilities=frozenset({"git_publish"}),
        network_approved=False,
    )
    tool = OpenPullRequestTool()
    blocked = await tool.execute({"title": "Ship feature X"}, base)
    assert blocked.status is ToolStatus.BLOCKED
    assert runner.calls == []

    opened = await tool.execute(
        {"title": "Ship feature X"},
        base.model_copy(
            update={
                "network_approved": True,
                "network_capabilities": frozenset({"git_publish"}),
            }
        ),
    )
    assert opened.status is ToolStatus.SUCCESS
    assert runner.calls[0]["permission"] is PermissionMode.FULL
    assert runner.calls[0]["approved"] is True


def test_default_registry_includes_open_pull_request() -> None:
    registry = build_default_registry()
    assert registry.get("open_pull_request") is not None
