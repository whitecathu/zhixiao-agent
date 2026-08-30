from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from zhixiao_agent.cli import app
from zhixiao_agent.cli_state import RunManifest
from zhixiao_agent.extensions import McpServer
from zhixiao_agent.hook_runtime import HookFailure, run_hooks
from zhixiao_agent.mcp_runtime import LocalMcpRuntime, mcp_metadata
from zhixiao_agent.types import PermissionMode


@pytest.mark.asyncio
async def test_hooks_require_trust_and_execute_permission(tmp_path: Path) -> None:
    with pytest.raises(HookFailure) as untrusted:
        await run_hooks(
            "before_run",
            [f'{sys.executable} -c "print(1)"'],
            workspace=tmp_path,
            trusted=False,
            permission=PermissionMode.EXECUTE,
            timeout=5,
        )
    assert untrusted.value.execution.status == "blocked"

    with pytest.raises(HookFailure) as readonly:
        await run_hooks(
            "before_run",
            [f'{sys.executable} -c "print(1)"'],
            workspace=tmp_path,
            trusted=True,
            permission=PermissionMode.READ_ONLY,
            timeout=5,
        )
    assert "execute" in readonly.value.execution.summary


@pytest.mark.asyncio
async def test_hook_sanitizes_environment_and_returns_structured_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TOP_SECRET", "must-not-leak")
    check_script = tmp_path / "check_env.py"
    check_script.write_text(
        "import os, sys\nsys.exit(9 if os.getenv('TOP_SECRET') else 0)\n",
        encoding="utf-8",
    )
    command = f'{sys.executable} {check_script}'
    success = await run_hooks(
        "before_run",
        [command],
        workspace=tmp_path,
        trusted=True,
        permission=PermissionMode.EXECUTE,
        timeout=5,
    )
    assert success[0].status == "succeeded"

    fail_script = tmp_path / "fail.py"
    fail_script.write_text(
        "import sys\nsys.stderr.write('bad')\nsys.exit(7)\n", encoding="utf-8"
    )
    with pytest.raises(HookFailure) as failed:
        await run_hooks(
            "after_run",
            [f'{sys.executable} {fail_script}'],
            workspace=tmp_path,
            trusted=True,
            permission=PermissionMode.EXECUTE,
            timeout=5,
        )
    assert failed.value.execution.status == "failed"
    assert failed.value.execution.exit_code == 7
    assert failed.value.execution.stderr == "bad"


@pytest.mark.asyncio
async def test_hook_timeout_is_structured(tmp_path: Path) -> None:
    sleep_script = tmp_path / "sleep.py"
    sleep_script.write_text("import time\ntime.sleep(3)\n", encoding="utf-8")
    with pytest.raises(HookFailure) as failed:
        await run_hooks(
            "after_run",
            [f'{sys.executable} {sleep_script}'],
            workspace=tmp_path,
            trusted=True,
            permission=PermissionMode.EXECUTE,
            timeout=1,
        )
    assert failed.value.execution.timed_out is True
    assert "timed out" in failed.value.execution.summary


@pytest.mark.asyncio
async def test_stdio_mcp_invokes_whitelisted_tool_and_resolves_secret_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "mcp_server.py"
    script.write_text(
        "import json, os, sys\n"
        "req=json.loads(sys.stdin.readline())\n"
        "print(json.dumps({'jsonrpc':'2.0','id':1,'result':"
        "{'tool':req['params']['name'],'token':os.environ.get('TOKEN')}}))\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MCP_TOKEN", "resolved-secret")
    runtime = LocalMcpRuntime(
        {
            "local": McpServer(
                transport="stdio",
                command=sys.executable,
                args=[str(script)],
                env={"TOKEN": "MCP_TOKEN"},
                tool_allowlist=["read"],
                call_timeout=5,
            )
        },
        workspace=tmp_path,
        network_approved=False,
    )

    result = await runtime("local", "read", {"path": "."})
    assert result == {"tool": "read", "token": "resolved-secret"}
    assert runtime.whitelist == ["local:read"]
    with pytest.raises(PermissionError):
        await runtime("local", "write", {})


@pytest.mark.asyncio
async def test_http_mcp_requires_network_approval_and_honors_timeout(
    tmp_path: Path,
) -> None:
    server = McpServer(
        transport="http",
        url="https://mcp.test/rpc",
        tool_allowlist=["search"],
        call_timeout=1,
    )
    blocked = LocalMcpRuntime(
        {"docs": server}, workspace=tmp_path, network_approved=False
    )
    with pytest.raises(PermissionError, match="network approval"):
        await blocked("docs", "search", {})

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["method"] == "tools/call"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})

    allowed = LocalMcpRuntime(
        {"docs": server},
        workspace=tmp_path,
        network_approved=True,
        http_transport=httpx.MockTransport(handler),
    )
    assert await allowed("docs", "search", {"q": "agent"}) == {"ok": True}


def test_mcp_metadata_includes_server_transports(tmp_path: Path) -> None:
    servers = {
        "local": McpServer(
            transport="stdio",
            command=sys.executable,
            tool_allowlist=["read"],
        ),
        "docs": McpServer(
            transport="http",
            url="https://mcp.test/rpc",
            tool_allowlist=["search"],
        ),
    }
    metadata = mcp_metadata(servers, workspace=tmp_path, network_approved=False)
    assert metadata["mcp_network_approved"] is False
    assert metadata["mcp_whitelist"] == ["docs:search", "local:read"]
    assert metadata["mcp_server_transports"] == {"local": "stdio", "docs": "http"}
    assert callable(metadata["mcp"])


def test_run_manifest_runtime_snapshot_contains_no_secrets() -> None:
    manifest = RunManifest(
        run_id="run-1",
        prompt="do work",
        workspace="C:/work",
        status="awaiting_approval",
        mode="code",
        permission="full",
        runner="docker",
        approval_policy="on_request",
        budget={"max_model_turns": 7, "max_tool_calls": 11, "max_tokens": 1000},
        allow_unverified="manual fixture",
        verification_commands=["pytest -q"],
        command_timeout=42,
        ops_capabilities=["mcp"],
        network_capabilities=["mcp"],
        trusted_workspace=True,
    )
    payload = manifest.model_dump_json()
    assert '"max_model_turns":7' in payload.replace(" ", "")
    assert "api_key" not in payload
    assert "secret" not in payload


def test_local_resume_reuses_trusted_hooks_from_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "state"
    workspace = tmp_path / "workspace"
    marker = workspace / "resume-hook.txt"
    hooks_dir = workspace / ".zhixiao"
    hooks_dir.mkdir(parents=True)
    script = workspace / "hook.py"
    script.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran', encoding='utf-8')\n",
        encoding="utf-8",
    )
    (hooks_dir / "hooks.toml").write_text(
        "[hooks]\nafter_run = "
        f"{json.dumps([f'{sys.executable} {script}'])}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ZHIXIAO_STATE_DIR", str(state_dir))
    runner = CliRunner()

    initial = runner.invoke(
        app,
        [
            "run",
            "implement hook resume test",
            "--workspace",
            str(workspace),
            "--permission",
            "full",
            "--offline",
            "--trust-workspace",
            "--output-format",
            "json",
        ],
    )
    assert initial.exit_code == 3, initial.output
    run_id = json.loads(initial.output)["run_id"]
    assert not marker.exists()

    resumed = runner.invoke(
        app,
        ["resume", run_id, "--offline", "--output-format", "json"],
    )
    assert resumed.exit_code == 0, resumed.output
    assert marker.read_text(encoding="utf-8") == "ran"
