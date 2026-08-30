from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .extensions import McpConfigStore, load_custom_commands
from .plugin import PluginHost
from .session_controller import WorkMode
from .skills import SkillManager, default_skill_roots
from .types import PermissionMode

REVIEW_PROMPT = (
    "Review uncommitted changes. Report only actionable findings with severity, "
    "file, line, evidence, and a concise remediation. Do not edit files."
)

BUILTIN_COMMANDS = (
    "status",
    "diff",
    "test",
    "model",
    "mcp",
    "skills",
    "help",
    "mode",
    "permissions",
    "workspace",
    "approve",
    "deny",
    "resume",
    "cancel",
    "review",
    "fork",
    "steer",
    "plugins",
)

HELP = """Commands:
/status /diff /test /model /mcp /skills /plugins /help
/mode [ask|plan|code|review] /permissions [read_only|edit|execute|full]
/workspace [PATH] /steer TEXT
/approve /deny /resume RUN_ID /cancel /review /fork RUN_ID
"""

_UNKNOWN = "Unknown command. Enter /help."
_TRUST_REQUIRED = (
    "Raising permission above read_only requires --trust-workspace."
)


@dataclass
class SlashContext:
    workspace: Path
    permission: PermissionMode
    mode: WorkMode
    trusted: bool
    settings: Any
    pending_run_id: str | None
    last_result: Any | None
    last_run_id: str | None
    busy: bool
    model_label: str
    host: PluginHost | None = None


@dataclass
class SlashResult:
    message: str
    kind: str = "info"
    prompt: str | None = None
    permission: PermissionMode | None = None
    mode: WorkMode | None = None
    workspace: Path | None = None
    run_id: str | None = None
    approved: bool | None = None


def dispatch_slash(raw: str, ctx: SlashContext) -> SlashResult:
    """Parse a slash command. Byte 0 must be `/`; never treat input as a prompt."""
    if not raw or raw[:1] != "/":
        return _error(_UNKNOWN)
    name, _, argument = raw[1:].partition(" ")
    name = name.strip()
    argument = argument.strip()
    if not name:
        return _error(_UNKNOWN)
    key = name.lower()
    if ctx.host is not None:
        return _dispatch_plugin_command(key, argument, ctx)
    handler = _HANDLERS.get(key)
    if handler is not None:
        return handler(argument, ctx)
    return _dispatch_custom(name, argument, ctx)


def _error(message: str) -> SlashResult:
    return SlashResult(message=message, kind="error")


def _dispatch_custom(name: str, argument: str, ctx: SlashContext) -> SlashResult:
    commands = load_custom_commands(ctx.workspace, trusted=ctx.trusted)
    command = commands.get(name) or commands.get(name.lower())
    if command is None:
        return _error(_UNKNOWN)
    mode: WorkMode | None = None
    try:
        mode = WorkMode(command.mode)
    except ValueError:
        mode = None
    return SlashResult(
        message=f"Running custom command /{command.name}",
        kind="start_run",
        prompt=command.expand(argument),
        mode=mode,
    )


def _dispatch_plugin_command(key: str, argument: str, ctx: SlashContext) -> SlashResult:
    host = ctx.host
    if host is None:
        return _error(_UNKNOWN)
    contribution = host.commands.get(key)
    if contribution is None:
        return _error(_UNKNOWN)
    if contribution.handler is not None:
        return cast(SlashResult, contribution.handler(argument, ctx))
    mode: WorkMode | None = None
    try:
        if contribution.mode:
            mode = WorkMode(contribution.mode)
    except ValueError:
        mode = None
    return SlashResult(
        message=f"Running custom command /{contribution.name}",
        kind="start_run",
        prompt=contribution.expand(argument),
        mode=mode,
    )


def _help(_argument: str, ctx: SlashContext) -> SlashResult:
    extra = ""
    if ctx.host is not None:
        plugin_commands = sorted(
            name
            for name, contribution in ctx.host.commands.items()
            if contribution.plugin != "core.commands"
        )
        if plugin_commands:
            extra = "\nPlugin commands: " + " ".join(f"/{name}" for name in plugin_commands)
    return SlashResult(message=HELP + extra, kind="help")


def _status(_argument: str, ctx: SlashContext) -> SlashResult:
    if ctx.busy:
        run = ctx.last_run_id or "in progress"
        return SlashResult(message=f"Busy; run {run} is active.", kind="status")
    if ctx.pending_run_id:
        return SlashResult(
            message=f"Run {ctx.pending_run_id}: awaiting_approval",
            kind="status",
        )
    if ctx.last_result is None:
        return SlashResult(
            message="No completed or paused run in this session.",
            kind="status",
        )
    run_id = _result_run_id(ctx.last_result) or ctx.last_run_id or "unknown"
    status = _result_status(ctx.last_result) or "unknown"
    return SlashResult(message=f"Run {run_id}: {status}", kind="status")


def _diff(_argument: str, ctx: SlashContext) -> SlashResult:
    diff = _result_field(ctx.last_result, "diff") or ""
    return SlashResult(message=str(diff) or "No diff.", kind="info")


def _test(_argument: str, ctx: SlashContext) -> SlashResult:
    if ctx.last_result is None:
        return SlashResult(message="No verification result.", kind="info")
    outcome = _verification_outcome(ctx.last_result)
    return SlashResult(message=f"Verification: {outcome}", kind="info")


def _model(_argument: str, ctx: SlashContext) -> SlashResult:
    return SlashResult(message=f"Model: {ctx.model_label}", kind="info")


def _mcp(_argument: str, ctx: SlashContext) -> SlashResult:
    names = sorted(McpConfigStore(ctx.settings.state_dir).load())
    listing = ", ".join(names) if names else "none"
    return SlashResult(message=f"MCP servers: {listing}", kind="info")


def _skills(_argument: str, ctx: SlashContext) -> SlashResult:
    manager = SkillManager(
        default_skill_roots(ctx.workspace, trusted_workspace=ctx.trusted)
    )
    names = sorted(manager.load())
    listing = ", ".join(names) if names else "none"
    return SlashResult(message=f"Skills: {listing}", kind="info")


def _mode(argument: str, ctx: SlashContext) -> SlashResult:
    if not argument:
        return SlashResult(message=f"Mode: {ctx.mode.value}", kind="mode")
    try:
        mode = WorkMode(argument.lower())
    except ValueError:
        return _error("Expected ask, plan, code, or review.")
    return SlashResult(message=f"Mode: {mode.value}", kind="mode", mode=mode)


def _permissions(argument: str, ctx: SlashContext) -> SlashResult:
    if not argument:
        return SlashResult(
            message=f"Permission: {ctx.permission.value}",
            kind="permission",
        )
    try:
        permission = PermissionMode(argument.lower())
    except ValueError:
        return _error("Expected read_only, edit, execute, or full.")
    if permission is not PermissionMode.READ_ONLY and not ctx.trusted:
        return _error(_TRUST_REQUIRED)
    return SlashResult(
        message=f"Permission: {permission.value}",
        kind="permission",
        permission=permission,
    )


def _workspace(argument: str, ctx: SlashContext) -> SlashResult:
    if not argument:
        return SlashResult(message=str(ctx.workspace), kind="workspace")
    return SlashResult(
        message=f"Workspace: {argument}",
        kind="workspace",
        workspace=Path(argument),
    )


def _approve(_argument: str, ctx: SlashContext) -> SlashResult:
    if not ctx.pending_run_id:
        return SlashResult(message="There is no run awaiting approval.", kind="error")
    return SlashResult(
        message="Approving the plan.",
        kind="approve",
        run_id=ctx.pending_run_id,
        approved=True,
    )


def _deny(_argument: str, ctx: SlashContext) -> SlashResult:
    if not ctx.pending_run_id:
        return SlashResult(message="There is no run awaiting approval.", kind="error")
    return SlashResult(
        message="Denying the plan.",
        kind="deny",
        run_id=ctx.pending_run_id,
        approved=False,
    )


def _resume(argument: str, _ctx: SlashContext) -> SlashResult:
    run_id, _, extra = argument.partition(" ")
    run_id = run_id.strip()
    if not run_id:
        return _error("Usage: /resume RUN_ID")
    del extra
    return SlashResult(
        message=f"Resuming {run_id}",
        kind="resume",
        run_id=run_id,
        approved=True,
    )


def _cancel(_argument: str, _ctx: SlashContext) -> SlashResult:
    return SlashResult(message="Cancelling the active run.", kind="cancel")


def _review(_argument: str, _ctx: SlashContext) -> SlashResult:
    return SlashResult(
        message="Starting a read-only review.",
        kind="start_run",
        prompt=REVIEW_PROMPT,
    )


def _fork(argument: str, _ctx: SlashContext) -> SlashResult:
    run_id, _, extra = argument.partition(" ")
    run_id = run_id.strip()
    if not run_id:
        return _error("Usage: /fork RUN_ID")
    extra = extra.strip()
    return SlashResult(
        message=f"Forking {run_id}",
        kind="fork",
        run_id=run_id,
        prompt=extra or None,
    )


def _steer(argument: str, _ctx: SlashContext) -> SlashResult:
    if not argument:
        return _error("Usage: /steer TEXT")
    return SlashResult(message="Steering the next turn.", kind="steer", prompt=argument)


def _plugins(_argument: str, ctx: SlashContext) -> SlashResult:
    if ctx.host is None:
        return SlashResult(message="Plugin host is not loaded.", kind="info")
    if not ctx.host.plugins:
        return SlashResult(message="Plugins: none", kind="info")
    lines = [
        f"{plugin.name} [{plugin.source}] {plugin.origin}" for plugin in ctx.host.plugins
    ]
    return SlashResult(message="Plugins:\n" + "\n".join(lines), kind="info")


def _result_field(result: Any, name: str) -> Any:
    if result is None:
        return None
    if isinstance(result, dict):
        return result.get(name)
    return getattr(result, name, None)


def _result_run_id(result: Any) -> str | None:
    value = _result_field(result, "run_id")
    return str(value) if value else None


def _enum_value(value: Any) -> str:
    if value is None:
        return ""
    raw = getattr(value, "value", value)
    return str(raw)


def _result_status(result: Any) -> str:
    return _enum_value(_result_field(result, "status"))


def _verification_outcome(result: Any) -> str:
    verification = _result_field(result, "verification")
    if verification is None:
        return "unknown"
    if isinstance(verification, dict):
        return str(verification.get("outcome", "unknown"))
    return _enum_value(getattr(verification, "outcome", None)) or "unknown"


_HANDLERS = {
    "help": _help,
    "status": _status,
    "diff": _diff,
    "test": _test,
    "model": _model,
    "mcp": _mcp,
    "skills": _skills,
    "mode": _mode,
    "permissions": _permissions,
    "workspace": _workspace,
    "approve": _approve,
    "deny": _deny,
    "resume": _resume,
    "cancel": _cancel,
    "review": _review,
    "fork": _fork,
    "steer": _steer,
    "plugins": _plugins,
}


def builtin_command_handlers() -> dict[str, Callable[[str, SlashContext], SlashResult]]:
    """Return the built-in slash handlers for the core.commands plugin."""
    return dict(_HANDLERS)
