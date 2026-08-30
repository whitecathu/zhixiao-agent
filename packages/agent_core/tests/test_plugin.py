from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from zhixiao_agent.cli import app
from zhixiao_agent.plugin import PluginError, load_plugin_tree
from zhixiao_agent.session_controller import ApprovalPolicy, WorkMode, local_runtime_bundle
from zhixiao_agent.settings import load_settings
from zhixiao_agent.slash import SlashContext, dispatch_slash
from zhixiao_agent.types import PermissionMode, RunBudget

ECHO_PLUGIN = """
from pydantic import BaseModel

from zhixiao_agent.plugin import PluginContext
from zhixiao_agent.tools.base import BaseTool
from zhixiao_agent.types import ToolResult

name = "echo"
inject = ("tools",)

class EchoInput(BaseModel):
    text: str = ""

class EchoTool(BaseTool):
    name = "echo_plugin"
    description = "Echo text from a workspace plugin"
    input_model = EchoInput

    async def execute(self, arguments, context):
        del context
        return ToolResult.ok(arguments.get("text") or "")

def apply(ctx: PluginContext) -> None:
    ctx.register_tool(EchoTool())
    ctx.register_command(
        "echo",
        description="Expand an echo prompt",
        template="Echo {{args}}",
        mode="ask",
    )
    ctx.register_prompt_section("echo", "You may call echo_plugin.")
    ctx.on("run/start", lambda payload: payload.setdefault("seen", True))
"""


def _host(workspace: Path, *, trusted: bool = False, **kwargs):
    return load_plugin_tree(
        workspace=workspace,
        trusted=trusted,
        user_root=workspace / "user-plugins",
        **kwargs,
    )


def _write_plugin(workspace: Path, source: str, *, name: str = "echo.py") -> Path:
    directory = workspace / ".zhixiao" / "plugins"
    directory.mkdir(parents=True)
    path = directory / name
    path.write_text(source, encoding="utf-8")
    return path


def _slash_ctx(tmp_path: Path, host) -> SlashContext:
    return SlashContext(
        workspace=tmp_path,
        permission=PermissionMode.READ_ONLY,
        mode=WorkMode.ASK,
        trusted=True,
        settings=None,
        pending_run_id=None,
        last_result=None,
        last_run_id=None,
        busy=False,
        model_label="offline",
        host=host,
    )


def test_builtin_tree_provides_core_seams(tmp_path: Path) -> None:
    host = _host(tmp_path)
    names = {plugin.name for plugin in host.plugins}
    assert names == {
        "core.tools",
        "core.commands",
        "core.skills",
        "core.mcp",
        "workspace.extensions",
    }
    assert "read_file" in host.tools.names()
    assert "help" in host.commands
    assert "plugins" in host.commands
    snapshot = host.snapshot()
    assert snapshot["trusted"] is False
    assert "read_file" in snapshot["seams"]["tools"]


def test_untrusted_workspace_skips_python_plugins(tmp_path: Path) -> None:
    _write_plugin(tmp_path, ECHO_PLUGIN)
    host = _host(tmp_path, trusted=False)
    assert "echo" not in {plugin.name for plugin in host.plugins}
    assert host.tools.get("echo_plugin") is None


def test_trusted_workspace_plugin_contributes_tool_command_and_prompt(
    tmp_path: Path,
) -> None:
    _write_plugin(tmp_path, ECHO_PLUGIN)
    host = _host(tmp_path, trusted=True)
    assert host.tools.get("echo_plugin") is not None
    assert "echo" in host.commands
    assert "You may call echo_plugin." in host.render_prompt()
    result = dispatch_slash("/echo hello", _slash_ctx(tmp_path, host))
    assert result.kind == "start_run"
    assert result.prompt == "Echo hello"
    seen: dict[str, bool] = {}
    host.emit("run/start", seen)
    assert seen["seen"] is True


def test_duplicate_tool_name_fails_loud(tmp_path: Path) -> None:
    _write_plugin(
        tmp_path,
        """
name = "dup"
inject = ("tools",)

def apply(ctx):
    from zhixiao_agent.tools.filesystem import ReadFileTool
    ctx.register_tool(ReadFileTool())
""",
    )
    with pytest.raises(PluginError, match="already registered"):
        _host(tmp_path, trusted=True)


def test_apply_exception_fails_loud(tmp_path: Path) -> None:
    _write_plugin(
        tmp_path,
        """
name = "boom"

def apply(ctx):
    raise RuntimeError("apply exploded")
""",
    )
    with pytest.raises(PluginError, match="apply exploded"):
        _host(tmp_path, trusted=True)


def test_unresolved_inject_fails_loud(tmp_path: Path) -> None:
    _write_plugin(
        tmp_path,
        """
name = "needs-prompt"
inject = ("prompt",)

def apply(ctx):
    return None
""",
    )
    with pytest.raises(PluginError, match="unresolved plugin inject"):
        _host(tmp_path, trusted=True)


def test_unknown_inject_seam_fails_loud(tmp_path: Path) -> None:
    _write_plugin(
        tmp_path,
        """
name = "bad-inject"
inject = ("shell",)

def apply(ctx):
    return None
""",
    )
    with pytest.raises(PluginError, match="unknown seam"):
        _host(tmp_path, trusted=True)


def test_manifest_missing_module_fails_loud(tmp_path: Path) -> None:
    zhixiao = tmp_path / ".zhixiao"
    zhixiao.mkdir()
    (zhixiao / "plugins.toml").write_text(
        '[[plugin]]\nname = "missing"\npath = "plugins/missing.py"\n',
        encoding="utf-8",
    )
    with pytest.raises(PluginError, match="not found"):
        _host(tmp_path, trusted=True)


def test_plugin_path_escape_fails_loud(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-plugin.py"
    outside.write_text("name = 'evil'\ndef apply(ctx):\n    return None\n", encoding="utf-8")
    zhixiao = tmp_path / ".zhixiao"
    zhixiao.mkdir()
    (zhixiao / "plugins.toml").write_text(
        '[[plugin]]\nname = "evil"\npath = "../outside-plugin.py"\n',
        encoding="utf-8",
    )
    with pytest.raises(PluginError, match="escapes"):
        _host(tmp_path, trusted=True)


def test_slash_plugins_lists_loaded_modules(tmp_path: Path) -> None:
    host = _host(tmp_path)
    result = dispatch_slash("/plugins", _slash_ctx(tmp_path, host))
    assert result.kind == "info"
    assert "core.tools" in result.message
    help_result = dispatch_slash("/help", _slash_ctx(tmp_path, host))
    assert "/plugins" in help_result.message


def test_workspace_markdown_commands_register_on_host(tmp_path: Path) -> None:
    commands = tmp_path / ".zhixiao" / "commands"
    commands.mkdir(parents=True)
    (commands / "fix.md").write_text(
        "---\nname: fix\nmode: code\n---\nFix {{args}} safely.",
        encoding="utf-8",
    )
    host = _host(tmp_path, trusted=True)
    result = dispatch_slash("/fix the parser", _slash_ctx(tmp_path, host))
    assert result.kind == "start_run"
    assert result.prompt == "Fix the parser safely."
    assert result.mode is WorkMode.CODE


def test_local_runtime_bundle_includes_plugin_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZHIXIAO_CONFIG_FILE", str(tmp_path / "user-config.toml"))
    monkeypatch.setenv("ZHIXIAO_STATE_DIR", str(tmp_path / "state"))
    _write_plugin(tmp_path, ECHO_PLUGIN)
    settings = load_settings(tmp_path)
    runtime, config, _hooks = local_runtime_bundle(
        settings=settings,
        workspace=tmp_path,
        permission=PermissionMode.READ_ONLY,
        mode=WorkMode.ASK,
        approval_policy=ApprovalPolicy.NEVER,
        approved=False,
        approve_ops=frozenset(),
        network=frozenset(),
        offline=True,
        runner="local",
        test_command=None,
        budget=RunBudget(),
        allow_unverified=None,
        trusted=True,
        command_timeout=30,
        plugin_host=_host(tmp_path, trusted=True, settings=settings),
    )
    assert runtime.registry.get("echo_plugin") is not None
    assert "echo_plugin" in (config.plugin_prompt or "")


def test_cli_plugins_list_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZHIXIAO_CONFIG_FILE", str(tmp_path / "user-config.toml"))
    result = CliRunner().invoke(
        app,
        ["plugins", "list", "--workspace", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    assert "core.tools" in result.stdout
    assert "read_file" in result.stdout


def test_cli_plugins_doctor_rejects_broken_plugin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZHIXIAO_CONFIG_FILE", str(tmp_path / "user-config.toml"))
    _write_plugin(
        tmp_path,
        """
name = "broken"
def apply(ctx):
    raise RuntimeError("nope")
""",
    )
    result = CliRunner().invoke(
        app,
        ["plugins", "doctor", "--workspace", str(tmp_path), "--trust-workspace"],
    )
    assert result.exit_code != 0
    assert "nope" in result.output
