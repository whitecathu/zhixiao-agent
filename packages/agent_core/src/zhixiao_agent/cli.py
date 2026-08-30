from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Awaitable, Callable
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from typer._click.core import Context

from .cli_state import SessionStore
from .extensions import (
    McpConfigStore,
    McpServer,
    expand_custom_command,
    load_hooks,
)
from .plugin import PluginError, load_plugin_tree
from .remote import TERMINAL_STATUSES, RemoteClient, RemoteError, ServerEvent
from .session_controller import (
    SCHEMA_VERSION,
    ApprovalPolicy,
    OfflineModel,
    WorkMode,
    build_model,
    execute_local,
    fork_local,
    interrupt_local,
    local_runtime_bundle,
    resume_local,
)
from .settings import (
    AgentSettings,
    is_workspace_trusted,
    load_settings,
    project_config_path,
    user_config_path,
)
from .skills import SkillManager, default_skill_roots
from .types import PermissionMode, RunBudget

__all__ = [
    "SCHEMA_VERSION",
    "ApprovalPolicy",
    "OfflineModel",
    "WorkMode",
    "app",
    "build_model",
    "execute_local",
    "fork_local",
    "interrupt_local",
    "local_runtime_bundle",
    "resume_local",
]

EXIT_SUCCESS = 0
EXIT_USAGE = 2
EXIT_APPROVAL = 3
EXIT_TASK_FAILED = 4
EXIT_REMOTE = 5
EXIT_TIMEOUT = 124
EXIT_INTERRUPTED = 130

_execute_local = execute_local


class OutputFormat(StrEnum):
    TEXT = "text"
    JSON = "json"
    JSONL = "jsonl"


class EventMode(StrEnum):
    AUTO = "auto"
    HUMAN = "human"
    JSONL = "jsonl"
    NONE = "none"


class RunnerBackend(StrEnum):
    LOCAL = "local"
    DOCKER = "docker"
    BUBBLEWRAP = "bubblewrap"


app = typer.Typer(
    name="zhixiao",
    help="Auditable AI full-stack engineering agent.",
    no_args_is_help=False,
    invoke_without_command=True,
    pretty_exceptions_enable=False,
)


class PromptFriendlyGroup(typer.core.TyperGroup):
    """Route an unknown first token to the TUI without stealing known subcommands."""

    def invoke(self, ctx: Context) -> Any:
        protected_args = list(ctx._protected_args)
        if protected_args and protected_args[0] not in self.commands:
            prompt_parts = [*protected_args, *ctx.args]
            ctx._protected_args = []
            ctx.args = []
            ctx.meta["initial_prompt"] = " ".join(prompt_parts)
        return super().invoke(ctx)


app.info.cls = PromptFriendlyGroup
runs_app = typer.Typer(help="Inspect and manage persisted task runs.")
config_app = typer.Typer(help="Inspect and validate layered configuration.")
mcp_app = typer.Typer(help="Manage local MCP server definitions.")
skills_app = typer.Typer(help="Inspect project and built-in skills.")
hooks_app = typer.Typer(help="Inspect trusted workspace hooks.")
plugins_app = typer.Typer(help="Inspect the composed plugin tree.")
app.add_typer(runs_app, name="runs")
app.add_typer(config_app, name="config")
app.add_typer(mcp_app, name="mcp")
app.add_typer(skills_app, name="skills")
app.add_typer(hooks_app, name="hooks")
app.add_typer(plugins_app, name="plugins")


@app.callback()
def main(
    ctx: typer.Context,
    workspace: Annotated[Path, typer.Option("--workspace", "-w")] = Path("."),
    offline: Annotated[bool, typer.Option("--offline")] = False,
    permission: Annotated[PermissionMode, typer.Option("--permission")] = PermissionMode.READ_ONLY,
    mode: Annotated[WorkMode, typer.Option("--mode")] = WorkMode.ASK,
    trust_workspace: Annotated[bool, typer.Option("--trust-workspace")] = False,
) -> None:
    if ctx.invoked_subcommand is None:
        from .tui import launch

        launch(
            initial_prompt=ctx.meta.get("initial_prompt"),
            workspace=workspace,
            offline=offline,
            permission=permission,
            mode=mode,
            trust_workspace=trust_workspace,
        )


def _settings_or_exit(
    workspace: Path | None = None,
    *,
    trust_workspace: bool = False,
    profile: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> AgentSettings:
    try:
        return load_settings(
            workspace,
            trusted_workspace=trust_workspace,
            profile=profile,
            overrides=overrides,
        )
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc


def _warn_deprecated_api_token(api_token: str | None) -> None:
    if api_token:
        typer.echo(
            "--api-token is supported for compatibility; prefer ZHIXIAO_API_TOKEN",
            err=True,
        )


def _resolve_prompt(
    positional: str | None,
    option: str | None,
    prompt_file: Path | None,
) -> str:
    selected = [positional is not None, option is not None, prompt_file is not None]
    if sum(selected) != 1:
        raise typer.BadParameter(
            "provide exactly one prompt source: PROMPT, --prompt, or --prompt-file"
        )
    if prompt_file is not None:
        if str(prompt_file) == "-":
            value = sys.stdin.read()
        else:
            try:
                value = prompt_file.read_text(encoding="utf-8")
            except OSError as exc:
                raise typer.BadParameter(f"cannot read prompt file {prompt_file}: {exc}") from exc
    else:
        value = positional if positional is not None else option or ""
        if value == "-":
            value = sys.stdin.read()
    value = value.strip()
    if not value:
        raise typer.BadParameter("prompt cannot be empty")
    return value


def _json_line(event: str, *, run_id: str, sequence: int, data: dict[str, Any]) -> str:
    return json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "sequence": sequence,
            "run_id": run_id,
            "event": event,
            "timestamp": data.pop("timestamp", None),
            "data": data,
        },
        ensure_ascii=False,
        default=str,
    )


def _emit_event(
    event: dict[str, Any],
    *,
    mode: EventMode,
    output_format: OutputFormat,
    quiet: bool,
) -> None:
    effective = EventMode.JSONL if output_format is OutputFormat.JSONL else mode
    if effective is EventMode.AUTO:
        effective = EventMode.NONE if output_format is OutputFormat.JSON else EventMode.HUMAN
    if effective is EventMode.NONE or quiet:
        return
    name = str(event.get("event", "message"))
    data = dict(event.get("data", {}))
    sequence = int(event.get("sequence", 0))
    run_id = str(event.get("run_id", data.get("run_id", "")))
    if effective is EventMode.JSONL:
        typer.echo(_json_line(name, run_id=run_id, sequence=sequence, data=data))
    else:
        summary = data.get("summary") or data.get("status") or data.get("node") or ""
        typer.echo(f"[{sequence:04d}] {name}{': ' + str(summary) if summary else ''}", err=True)


def _write_result(
    result: dict[str, Any],
    *,
    output_format: OutputFormat,
    output: Path | None,
    no_color: bool,
    quiet: bool,
) -> None:
    if output_format is OutputFormat.JSONL:
        rendered = _json_line(
            "result",
            run_id=str(result.get("run_id", "")),
            sequence=int(result.get("sequence", len(result.get("events", [])) + 1)),
            data={key: value for key, value in result.items() if key != "events"},
        )
    elif output_format is OutputFormat.JSON:
        rendered = json.dumps(result, ensure_ascii=False, default=str, sort_keys=True)
    else:
        rendered = _result_text(result, no_color=no_color)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    if not quiet:
        typer.echo(rendered)


def _result_text(result: dict[str, Any], *, no_color: bool) -> str:
    console = Console(record=True, color_system=None if no_color else "auto", force_terminal=False)
    console.print(
        Panel(
            f"[bold]{result.get('status', 'unknown')}[/bold]\n{result.get('summary', '')}",
            title="Zhixiao",
        )
    )
    if result.get("plan"):
        console.print("[bold]Plan[/bold]")
        for index, step in enumerate(result["plan"], 1):
            console.print(f"  {index}. {step}")
    verification = result.get("verification", {})
    if verification:
        console.print(f"[bold]Verification[/bold] {verification.get('outcome', 'unknown')}")
    if result.get("diff"):
        console.print(Panel(str(result["diff"]), title="Git diff"))
    return console.export_text().rstrip()


def _exit_for_status(status: str) -> int:
    if status in {"succeeded", "completed"}:
        return EXIT_SUCCESS
    if status in {"awaiting_approval", "blocked"}:
        return EXIT_APPROVAL
    if status == "interrupted":
        return EXIT_INTERRUPTED
    return EXIT_TASK_FAILED


@app.command()
def run(
    task: Annotated[str | None, typer.Argument(help="Engineering task or '-' for stdin")] = None,
    prompt: Annotated[str | None, typer.Option("--prompt", "-p", help="Engineering task")] = None,
    prompt_file: Annotated[
        Path | None, typer.Option("--prompt-file", help="UTF-8 prompt file or '-' for stdin")
    ] = None,
    workspace: Annotated[Path, typer.Option("--workspace", "-w")] = Path("."),
    permission: Annotated[PermissionMode, typer.Option("--permission")] = PermissionMode.READ_ONLY,
    mode: Annotated[
        WorkMode, typer.Option("--mode", help="ask/plan stay read-only; code implements")
    ] = WorkMode.CODE,
    approval_policy: Annotated[
        ApprovalPolicy, typer.Option("--approval-policy")
    ] = ApprovalPolicy.ON_REQUEST,
    runner: Annotated[RunnerBackend | None, typer.Option("--runner")] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Approve the generated plan")] = False,
    approve_ops: Annotated[
        list[str] | None,
        typer.Option("--approve-ops", help="Approve a named high-risk capability"),
    ] = None,
    network: Annotated[
        list[str] | None,
        typer.Option("--approve-network", help="Approve a named network capability"),
    ] = None,
    offline: Annotated[
        bool, typer.Option("--offline", help="Do not call an external model")
    ] = False,
    output_format: Annotated[
        OutputFormat, typer.Option("--output-format")
    ] = OutputFormat.TEXT,
    output_json: Annotated[
        bool, typer.Option("--json", help="Alias for --output-format json")
    ] = False,
    events: Annotated[EventMode, typer.Option("--events")] = EventMode.AUTO,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    quiet: Annotated[bool, typer.Option("--quiet", "-q")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
    no_color: Annotated[bool, typer.Option("--no-color")] = False,
    test_command: Annotated[str | None, typer.Option("--test-command")] = None,
    api_url: Annotated[str | None, typer.Option("--api-url", help="Remote API URL")] = None,
    api_token: Annotated[
        str | None,
        typer.Option("--api-token", help="Deprecated; prefer ZHIXIAO_API_TOKEN", hidden=True),
    ] = None,
    space_id: Annotated[int | None, typer.Option("--space-id")] = None,
    repository_id: Annotated[int | None, typer.Option("--repository-id")] = None,
    profile: Annotated[str | None, typer.Option("--profile")] = None,
    trust_workspace: Annotated[
        bool, typer.Option("--trust-workspace", help="Enable project config and extensions")
    ] = False,
    wait_timeout: Annotated[float, typer.Option("--wait-timeout", min=0.1)] = 900,
    max_model_rounds: Annotated[int, typer.Option("--max-model-rounds", min=1)] = 30,
    max_tool_calls: Annotated[int, typer.Option("--max-tool-calls", min=1)] = 50,
    max_tokens: Annotated[int | None, typer.Option("--max-tokens", min=1)] = None,
    max_cost_usd: Annotated[float | None, typer.Option("--max-cost-usd", min=0)] = None,
    allow_unverified: Annotated[
        str | None, typer.Option("--allow-unverified", help="Required waiver reason")
    ] = None,
    interrupt_on_exit: Annotated[bool, typer.Option("--interrupt-on-exit")] = False,
) -> None:
    """Run one task locally or through a remote Zhixiao API."""
    resolved_prompt = _resolve_prompt(task, prompt, prompt_file)
    resolved = workspace.resolve()
    if not resolved.is_dir():
        raise typer.BadParameter(f"workspace is not a directory: {resolved}")
    settings = _settings_or_exit(
        resolved,
        trust_workspace=trust_workspace,
        profile=profile,
        overrides={
            "runner_backend": runner.value if runner else None,
            "api_url": api_url,
            "space_id": space_id,
        },
    )
    effective_format = OutputFormat.JSON if output_json else output_format
    trusted = trust_workspace or is_workspace_trusted(resolved, settings)
    if verbose:
        typer.echo(f"workspace={resolved}", err=True)
        typer.echo(f"permission={permission.value}", err=True)
        typer.echo(f"mode={mode.value}", err=True)
        typer.echo(f"trusted={trusted}", err=True)
        typer.echo(f"offline={offline}", err=True)
    if not trusted and permission is not PermissionMode.READ_ONLY:
        typer.echo(
            "workspace is not trusted; use --trust-workspace to enable edit/execute modes",
            err=True,
        )
        raise typer.Exit(EXIT_APPROVAL)
    original_prompt = resolved_prompt
    resolved_prompt = expand_custom_command(resolved_prompt, resolved, trusted=trusted)
    effective_api_url = api_url or settings.api_url or None
    _warn_deprecated_api_token(api_token)
    effective_token = api_token or settings.api_token or None
    remote_client: RemoteClient | None = None
    try:
        if effective_api_url:
            if repository_id is None:
                raise typer.BadParameter("--repository-id is required with --api-url")
            remote_client = RemoteClient(
                effective_api_url,
                token=effective_token,
                space_id=space_id or settings.space_id,
            )
            payload = asyncio.run(
                _execute_remote(
                    remote_client,
                    prompt=resolved_prompt,
                    permission=permission,
                    repository_id=repository_id,
                    approve=yes,
                    wait_timeout=wait_timeout,
                    budget=RunBudget(
                        max_model_turns=max_model_rounds,
                        max_tool_calls=max_tool_calls,
                        max_tokens=max_tokens or 200_000,
                        max_cost_usd=max_cost_usd,
                        max_duration_seconds=max(int(wait_timeout), 1),
                    ),
                    allow_unverified=allow_unverified,
                    verification_commands=[test_command] if test_command else [],
                    on_event=lambda item: _remote_event_callback(
                        item, mode=events, output_format=effective_format, quiet=quiet
                    ),
                )
            )
        else:
            payload = asyncio.run(
                execute_local(
                    original_prompt,
                    workspace=resolved,
                    settings=settings,
                    permission=permission,
                    mode=mode,
                    approval_policy=approval_policy,
                    approved=yes,
                    approve_ops=frozenset(approve_ops or []),
                    network=frozenset(network or []),
                    offline=offline,
                    runner=runner.value if runner else settings.runner_backend,
                    test_command=test_command,
                    max_model_rounds=max_model_rounds,
                    max_tool_calls=max_tool_calls,
                    max_tokens=max_tokens,
                    max_cost_usd=max_cost_usd,
                    allow_unverified=allow_unverified,
                    trusted=trusted,
                    on_event=lambda item: _local_event_callback(
                        item, mode=events, output_format=effective_format, quiet=quiet
                    ),
                )
            )
    except TimeoutError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_TIMEOUT) from exc
    except KeyboardInterrupt as exc:
        if effective_api_url and interrupt_on_exit:
            if remote_client is not None and remote_client.last_run_id:
                try:
                    asyncio.run(remote_client.interrupt(remote_client.last_run_id))
                except (RemoteError, httpx.HTTPError) as interrupt_error:
                    typer.echo(f"remote interrupt failed: {interrupt_error}", err=True)
                else:
                    typer.echo(
                        f"interrupted remote run {remote_client.last_run_id}", err=True
                    )
            else:
                typer.echo("interrupted before the remote run id was received", err=True)
        else:
            suffix = (
                f"; run id {remote_client.last_run_id}"
                if remote_client is not None and remote_client.last_run_id
                else ""
            )
            typer.echo(f"detached; the run may continue remotely{suffix}", err=True)
        raise typer.Exit(EXIT_INTERRUPTED) from exc
    except (RemoteError, httpx.HTTPError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_REMOTE) from exc
    _write_result(
        payload,
        output_format=effective_format,
        output=output,
        no_color=no_color,
        quiet=quiet,
    )
    exit_code = _exit_for_status(str(payload.get("status", "failed")))
    if exit_code:
        raise typer.Exit(exit_code)


async def _local_event_callback(
    event: dict[str, Any], *, mode: EventMode, output_format: OutputFormat, quiet: bool
) -> None:
    _emit_event(event, mode=mode, output_format=output_format, quiet=quiet)


async def _remote_event_callback(
    event: ServerEvent, *, mode: EventMode, output_format: OutputFormat, quiet: bool
) -> None:
    sequence = _sequence_from_event_id(event.id)
    _emit_event(
        {
            "sequence": sequence,
            "run_id": str(event.data.get("run_id", "")),
            "event": event.event,
            "data": dict(event.data),
        },
        mode=mode,
        output_format=output_format,
        quiet=quiet,
    )


def _sequence_from_event_id(event_id: str | None) -> int:
    if not event_id:
        return 0
    try:
        return int(event_id.split("-", 1)[0])
    except ValueError:
        return 0


async def _execute_remote(
    client: RemoteClient,
    *,
    prompt: str,
    permission: PermissionMode,
    repository_id: int,
    approve: bool,
    wait_timeout: float,
    budget: RunBudget,
    allow_unverified: str | None,
    verification_commands: list[str],
    on_event: Callable[[ServerEvent], Awaitable[None]],
) -> dict[str, Any]:
    run_data = await client.create_run(
        prompt,
        permission.value,
        repository_id,
        budget=budget.model_dump(mode="json"),
        allow_unverified=allow_unverified,
        verification_commands=verification_commands,
    )
    run_id = run_data["id"]
    if run_data.get("status") == "awaiting_approval":
        if not approve:
            return run_data
        pending = [
            item for item in await client.approvals(run_id) if item.get("status") == "pending"
        ]
        if not pending:
            raise RemoteError(f"run {run_id} awaits approval but no pending approval was returned")
        await client.decide(pending[0]["id"], True)
    return await client.follow(run_id, wait_timeout=wait_timeout, on_event=on_event)


def _remote_from_options(api_url: str, api_token: str | None, space_id: int) -> RemoteClient:
    return RemoteClient(api_url, token=api_token, space_id=space_id)


@app.command()
def resume(
    run_id: Annotated[str, typer.Argument()],
    approve: Annotated[bool, typer.Option("--approve/--deny")] = True,
    offline: Annotated[bool, typer.Option("--offline")] = False,
    api_url: Annotated[str | None, typer.Option("--api-url")] = None,
    api_token: Annotated[str | None, typer.Option("--api-token", hidden=True)] = None,
    space_id: Annotated[int, typer.Option("--space-id")] = 1,
    output_format: Annotated[OutputFormat, typer.Option("--output-format")] = OutputFormat.TEXT,
) -> None:
    """Resume a local approval checkpoint or an interrupted remote run."""
    settings = _settings_or_exit()
    _warn_deprecated_api_token(api_token)
    try:
        if api_url:
            payload = asyncio.run(
                _resume_remote(_remote_from_options(api_url, api_token, space_id), run_id)
            )
        else:
            payload = asyncio.run(
                resume_local(run_id, settings=settings, approved=approve, offline=offline)
            )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except (RemoteError, httpx.HTTPError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_REMOTE) from exc
    _write_result(payload, output_format=output_format, output=None, no_color=False, quiet=False)
    code = _exit_for_status(str(payload.get("status", "failed")))
    if code:
        raise typer.Exit(code)


async def _resume_remote(
    client: RemoteClient,
    run_id: str,
    *,
    wait_timeout: float = 900,
    on_event: Callable[[ServerEvent], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    resumed = await client.resume(run_id)
    if str(resumed.get("status")) in {"succeeded", "failed", "cancelled"}:
        return resumed
    return await client.follow(run_id, wait_timeout=wait_timeout, on_event=on_event)


async def _fork_remote(
    client: RemoteClient,
    run_id: str,
    overrides: dict[str, Any],
    *,
    wait_timeout: float = 900,
    on_event: Callable[[ServerEvent], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    payload = await client.fork(run_id, overrides)
    if str(payload.get("status")) in TERMINAL_STATUSES:
        return payload
    follow_id = payload.get("id") or payload.get("run_id") or run_id
    return await client.follow(follow_id, wait_timeout=wait_timeout, on_event=on_event)


async def _approve_remote(
    client: RemoteClient,
    run_id: str,
    approval_id: str,
    approved: bool,
    *,
    wait_timeout: float = 900,
    on_event: Callable[[ServerEvent], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    payload = await client.decide(approval_id, approved)
    follow_id = payload.get("run_id") or payload.get("id") or run_id
    if str(payload.get("status")) in TERMINAL_STATUSES:
        return payload
    return await client.follow(follow_id, wait_timeout=wait_timeout, on_event=on_event)


@runs_app.command("list")
def runs_list(
    api_url: Annotated[str | None, typer.Option("--api-url")] = None,
    api_token: Annotated[str | None, typer.Option("--api-token", hidden=True)] = None,
    space_id: Annotated[int, typer.Option("--space-id")] = 1,
    output_format: Annotated[OutputFormat, typer.Option("--output-format")] = OutputFormat.TEXT,
) -> None:
    settings = _settings_or_exit()
    _warn_deprecated_api_token(api_token)
    items = (
        asyncio.run(_remote_from_options(api_url, api_token, space_id).list_runs())
        if api_url
        else [item.model_dump(mode="json") for item in SessionStore(settings.state_dir).list()]
    )
    if output_format is not OutputFormat.TEXT:
        typer.echo(json.dumps(items, ensure_ascii=False, default=str, sort_keys=True))
        return
    table = Table("Run", "Status", "Workspace", "Updated", title="Zhixiao runs")
    for item in items:
        table.add_row(
            str(item.get("run_id", item.get("id", ""))),
            str(item.get("status", "")),
            str(item.get("workspace", item.get("workspace_id", ""))),
            str(item.get("updated_at", "")),
        )
    Console().print(table)


@runs_app.command("show")
def runs_show(
    run_id: Annotated[str, typer.Argument()],
    api_url: Annotated[str | None, typer.Option("--api-url")] = None,
    api_token: Annotated[str | None, typer.Option("--api-token", hidden=True)] = None,
    space_id: Annotated[int, typer.Option("--space-id")] = 1,
) -> None:
    settings = _settings_or_exit()
    _warn_deprecated_api_token(api_token)
    if api_url:
        payload = asyncio.run(_remote_from_options(api_url, api_token, space_id).get_run(run_id))
    else:
        item = SessionStore(settings.state_dir).get(run_id)
        if item is None:
            raise typer.BadParameter(f"local run not found: {run_id}")
        payload = item.model_dump(mode="json")
    typer.echo(json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True))


@runs_app.command("delete")
def runs_delete(run_id: Annotated[str, typer.Argument()]) -> None:
    """Delete a local run manifest. Runtime checkpoints are retained for audit/recovery."""
    settings = _settings_or_exit()
    if not SessionStore(settings.state_dir).delete(run_id):
        raise typer.BadParameter(f"local run not found: {run_id}")
    typer.echo(f"deleted local run index {run_id}; checkpoint retained")


@app.command("fork")
def fork_run(
    run_id: Annotated[str, typer.Argument()],
    prompt: Annotated[str | None, typer.Option("--prompt")] = None,
    offline: Annotated[bool, typer.Option("--offline")] = False,
    api_url: Annotated[str | None, typer.Option("--api-url")] = None,
    api_token: Annotated[str | None, typer.Option("--api-token", hidden=True)] = None,
    space_id: Annotated[int, typer.Option("--space-id")] = 1,
) -> None:
    """Create a child run from an existing local or remote run."""
    _warn_deprecated_api_token(api_token)
    try:
        if api_url:
            overrides = {"prompt": prompt} if prompt is not None else {}
            payload = asyncio.run(
                _fork_remote(
                    _remote_from_options(api_url, api_token, space_id),
                    run_id,
                    overrides,
                )
            )
        else:
            payload = asyncio.run(
                fork_local(
                    run_id,
                    settings=_settings_or_exit(),
                    prompt=prompt,
                    offline=offline,
                    on_event=_ignore_event,
                )
            )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except (RemoteError, httpx.HTTPError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_REMOTE) from exc
    _write_result(payload, output_format=OutputFormat.JSON, output=None, no_color=True, quiet=False)
    code = _exit_for_status(str(payload.get("status")))
    if code:
        raise typer.Exit(code)


async def _ignore_event(event: dict[str, Any]) -> None:
    del event


@app.command()
def events(
    run_id: Annotated[str, typer.Argument()],
    follow: Annotated[bool, typer.Option("--follow/--no-follow")] = False,
    cursor: Annotated[str | None, typer.Option("--cursor")] = None,
    api_url: Annotated[str | None, typer.Option("--api-url")] = None,
    api_token: Annotated[str | None, typer.Option("--api-token", hidden=True)] = None,
    space_id: Annotated[int, typer.Option("--space-id")] = 1,
) -> None:
    """Replay local events or follow the remote SSE stream as JSONL."""
    _warn_deprecated_api_token(api_token)
    if api_url:
        client = _remote_from_options(api_url, api_token, space_id)
        if follow:
            asyncio.run(
                client.follow(
                    run_id,
                    cursor=cursor,
                    on_event=lambda item: _remote_event_callback(
                        item, mode=EventMode.JSONL, output_format=OutputFormat.JSONL, quiet=False
                    ),
                )
            )
        else:
            typer.echo(json.dumps(asyncio.run(client.get_run(run_id)), ensure_ascii=False))
        return
    settings = _settings_or_exit()
    manifest = SessionStore(settings.state_dir).get(run_id)
    if manifest is None:
        raise typer.BadParameter(f"local run not found: {run_id}")
    for event in manifest.result.get("events", []):
        if cursor and int(event.get("sequence", 0)) <= int(cursor):
            continue
        _emit_event(event, mode=EventMode.JSONL, output_format=OutputFormat.JSONL, quiet=False)
    if follow and manifest.status not in {"succeeded", "failed", "interrupted"}:
        typer.echo(
            "local follow only replays persisted events; use TUI for a live local run",
            err=True,
        )


@app.command()
def approve(
    run_id: Annotated[str, typer.Argument()],
    approval_id: Annotated[str | None, typer.Argument()] = None,
    deny: Annotated[bool, typer.Option("--deny")] = False,
    api_url: Annotated[str | None, typer.Option("--api-url")] = None,
    api_token: Annotated[str | None, typer.Option("--api-token", hidden=True)] = None,
    space_id: Annotated[int, typer.Option("--space-id")] = 1,
    offline: Annotated[bool, typer.Option("--offline")] = False,
) -> None:
    """Approve or deny a local checkpoint, or a remote pending approval."""
    _warn_deprecated_api_token(api_token)
    if api_url:
        if approval_id is None:
            raise typer.BadParameter("APPROVAL_ID is required for remote approval")
        try:
            payload = asyncio.run(
                _approve_remote(
                    _remote_from_options(api_url, api_token, space_id),
                    run_id,
                    approval_id,
                    not deny,
                )
            )
        except (RemoteError, httpx.HTTPError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_REMOTE) from exc
        typer.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return
    resume(run_id, approve=not deny, offline=offline, api_url=None, api_token=None, space_id=1)


@app.command()
def interrupt(
    run_id: Annotated[str, typer.Argument()],
    api_url: Annotated[str | None, typer.Option("--api-url")] = None,
    api_token: Annotated[str | None, typer.Option("--api-token", hidden=True)] = None,
    space_id: Annotated[int, typer.Option("--space-id")] = 1,
) -> None:
    """Interrupt a local run via a cooperative stop file, or a remote run via the API."""
    _warn_deprecated_api_token(api_token)
    if api_url:
        payload = asyncio.run(_remote_from_options(api_url, api_token, space_id).interrupt(run_id))
        typer.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return
    try:
        payload = interrupt_local(run_id, settings=_settings_or_exit())
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(payload, ensure_ascii=False, default=str))


@app.command()
def artifacts(
    run_id: Annotated[str, typer.Argument()],
    api_url: Annotated[str | None, typer.Option("--api-url")] = None,
    api_token: Annotated[str | None, typer.Option("--api-token", hidden=True)] = None,
    space_id: Annotated[int, typer.Option("--space-id")] = 1,
) -> None:
    """List artifacts for a local or remote run."""
    _warn_deprecated_api_token(api_token)
    if api_url:
        payload: Any = asyncio.run(
            _remote_from_options(api_url, api_token, space_id).artifacts(run_id)
        )
    else:
        settings = _settings_or_exit()
        manifest = SessionStore(settings.state_dir).get(run_id)
        if manifest is None:
            raise typer.BadParameter(f"local run not found: {run_id}")
        payload = manifest.result.get("artifacts", [])
    typer.echo(json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True))


@app.command()
def review(
    workspace: Annotated[Path, typer.Option("--workspace", "-w")] = Path("."),
    uncommitted: Annotated[bool, typer.Option("--uncommitted")] = False,
    base: Annotated[str | None, typer.Option("--base")] = None,
    commit: Annotated[str | None, typer.Option("--commit")] = None,
    offline: Annotated[bool, typer.Option("--offline")] = False,
) -> None:
    """Review a Git change through the read-only agent workflow."""
    choices = sum([uncommitted, base is not None, commit is not None])
    if choices != 1:
        raise typer.BadParameter("choose exactly one of --uncommitted, --base, or --commit")
    target = "uncommitted changes" if uncommitted else (f"changes since {base}" if base else commit)
    prompt = (
        f"Review {target}. Report only actionable findings with severity, file, line, evidence, "
        "and a concise remediation. Do not edit files."
    )
    settings = _settings_or_exit(workspace)
    payload = asyncio.run(
        _execute_local(
            prompt,
            workspace=workspace.resolve(),
            settings=settings,
            permission=PermissionMode.READ_ONLY,
            mode=WorkMode.REVIEW,
            approval_policy=ApprovalPolicy.NEVER,
            approved=False,
            approve_ops=frozenset(),
            network=frozenset(),
            offline=offline,
            runner=settings.runner_backend,
            test_command=None,
            max_model_rounds=20,
            max_tool_calls=60,
            max_tokens=None,
            max_cost_usd=None,
            allow_unverified=None,
            trusted=False,
            on_event=_ignore_event,
        )
    )
    _write_result(
        payload,
        output_format=OutputFormat.TEXT,
        output=None,
        no_color=False,
        quiet=False,
    )


@config_app.command("show")
def config_show(
    workspace: Annotated[Path, typer.Option("--workspace", "-w")] = Path("."),
    trust_workspace: Annotated[bool, typer.Option("--trust-workspace")] = False,
    profile: Annotated[str | None, typer.Option("--profile")] = None,
) -> None:
    settings = _settings_or_exit(workspace, trust_workspace=trust_workspace, profile=profile)
    typer.echo(json.dumps(settings.redacted(), ensure_ascii=False, default=str, sort_keys=True))


@config_app.command("path")
def config_path(workspace: Annotated[Path, typer.Option("--workspace", "-w")] = Path(".")) -> None:
    typer.echo(f"user={user_config_path()}")
    typer.echo(f"project={project_config_path(workspace)}")


@config_app.command("validate")
def config_validate(
    workspace: Annotated[Path, typer.Option("--workspace", "-w")] = Path("."),
    trust_workspace: Annotated[bool, typer.Option("--trust-workspace")] = False,
) -> None:
    settings = _settings_or_exit(workspace, trust_workspace=trust_workspace)
    trusted = trust_workspace or is_workspace_trusted(workspace, settings)
    try:
        load_plugin_tree(workspace=workspace.resolve(), trusted=trusted, settings=settings)
    except PluginError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo("configuration is valid")


@mcp_app.command("add")
def mcp_add(
    name: Annotated[str, typer.Argument()],
    transport: Annotated[str, typer.Option("--transport")] = "stdio",
    command: Annotated[str | None, typer.Option("--command")] = None,
    arg: Annotated[list[str] | None, typer.Option("--arg")] = None,
    url: Annotated[str | None, typer.Option("--url")] = None,
    env: Annotated[list[str] | None, typer.Option("--env", help="NAME=ENV_VAR reference")] = None,
    allow_tool: Annotated[list[str] | None, typer.Option("--allow-tool")] = None,
) -> None:
    settings = _settings_or_exit()
    references: dict[str, str] = {}
    for value in env or []:
        key, separator, reference = value.partition("=")
        if not separator:
            raise typer.BadParameter("--env must use NAME=ENV_VAR")
        references[key] = reference
    try:
        server = McpServer.model_validate(
            {
                "transport": transport,
                "command": command,
                "args": arg or [],
                "url": url,
                "env": references,
                "tool_allowlist": allow_tool or [],
            }
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if server.transport == "stdio" and not server.command:
        raise typer.BadParameter("--command is required for stdio transport")
    if server.transport == "http" and not server.url:
        raise typer.BadParameter("--url is required for http transport")
    McpConfigStore(settings.state_dir).add(name, server)
    typer.echo(f"saved MCP server {name}")


@mcp_app.command("list")
def mcp_list() -> None:
    settings = _settings_or_exit()
    payload = {
        name: server.model_dump(mode="json", exclude_none=True)
        for name, server in McpConfigStore(settings.state_dir).load().items()
    }
    typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))


@mcp_app.command("remove")
def mcp_remove(name: Annotated[str, typer.Argument()]) -> None:
    settings = _settings_or_exit()
    if not McpConfigStore(settings.state_dir).remove(name):
        raise typer.BadParameter(f"MCP server not found: {name}")
    typer.echo(f"removed MCP server {name}")


@mcp_app.command("test")
def mcp_test(name: Annotated[str, typer.Argument()]) -> None:
    settings = _settings_or_exit()
    server = McpConfigStore(settings.state_dir).load().get(name)
    if server is None:
        raise typer.BadParameter(f"MCP server not found: {name}")
    ok, summary = server.diagnose()
    typer.echo(json.dumps({"name": name, "ok": ok, "summary": summary}, ensure_ascii=False))
    if not ok:
        raise typer.Exit(EXIT_TASK_FAILED)


@skills_app.command("list")
def skills_list(
    workspace: Annotated[Path, typer.Option("--workspace", "-w")] = Path("."),
    trust_workspace: Annotated[bool, typer.Option("--trust-workspace")] = False,
) -> None:
    manager = SkillManager(default_skill_roots(workspace, trusted_workspace=trust_workspace))
    payload = [
        {"name": skill.name, "description": skill.description, "path": str(skill.path)}
        for skill in manager.load().values()
    ]
    typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))


@skills_app.command("show")
def skills_show(
    name: Annotated[str, typer.Argument()],
    workspace: Annotated[Path, typer.Option("--workspace", "-w")] = Path("."),
    trust_workspace: Annotated[bool, typer.Option("--trust-workspace")] = False,
) -> None:
    manager = SkillManager(default_skill_roots(workspace, trusted_workspace=trust_workspace))
    skill = manager.load().get(name)
    if skill is None:
        raise typer.BadParameter(f"skill not found: {name}")
    typer.echo(f"# {skill.name}\n\n{skill.description}\n\n{skill.instructions}")


@skills_app.command("validate")
def skills_validate(
    workspace: Annotated[Path, typer.Option("--workspace", "-w")] = Path("."),
    trust_workspace: Annotated[bool, typer.Option("--trust-workspace")] = False,
) -> None:
    manager = SkillManager(default_skill_roots(workspace, trusted_workspace=trust_workspace))
    loaded = manager.load()
    if any(not skill.instructions.strip() for skill in loaded.values()):
        raise typer.BadParameter("one or more skills have empty instructions")
    typer.echo(f"validated {len(loaded)} skills")


@hooks_app.command("list")
def hooks_list(
    workspace: Annotated[Path, typer.Option("--workspace", "-w")] = Path("."),
    trust_workspace: Annotated[bool, typer.Option("--trust-workspace")] = False,
) -> None:
    hooks = load_hooks(workspace, trusted=trust_workspace)
    typer.echo(json.dumps(hooks, ensure_ascii=False, sort_keys=True))


@hooks_app.command("validate")
def hooks_validate(
    workspace: Annotated[Path, typer.Option("--workspace", "-w")] = Path("."),
    trust_workspace: Annotated[bool, typer.Option("--trust-workspace")] = False,
) -> None:
    hooks = load_hooks(workspace, trusted=trust_workspace)
    typer.echo(f"validated {sum(map(len, hooks.values()))} hooks")


@plugins_app.command("list")
def plugins_list(
    workspace: Annotated[Path, typer.Option("--workspace", "-w")] = Path("."),
    trust_workspace: Annotated[bool, typer.Option("--trust-workspace")] = False,
) -> None:
    """Print the composed plugin tree and contribution seams as JSON."""
    host = _plugin_host(workspace, trust_workspace=trust_workspace)
    typer.echo(json.dumps(host.snapshot(), ensure_ascii=False, indent=2))


@plugins_app.command("doctor")
def plugins_doctor(
    workspace: Annotated[Path, typer.Option("--workspace", "-w")] = Path("."),
    trust_workspace: Annotated[bool, typer.Option("--trust-workspace")] = False,
) -> None:
    """Load the plugin tree and fail when composition is invalid."""
    host = _plugin_host(workspace, trust_workspace=trust_workspace)
    typer.echo(f"validated {len(host.plugins)} plugins")


def _plugin_host(workspace: Path, *, trust_workspace: bool) -> Any:
    settings = _settings_or_exit(workspace, trust_workspace=trust_workspace)
    trusted = trust_workspace or is_workspace_trusted(workspace, settings)
    try:
        return load_plugin_tree(
            workspace=workspace.resolve(),
            trusted=trusted,
            settings=settings,
        )
    except PluginError as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command()
def doctor(
    workspace: Annotated[Path, typer.Option("--workspace", "-w")] = Path("."),
    output_json: Annotated[bool, typer.Option("--json")] = False,
    api_url: Annotated[str | None, typer.Option("--api-url")] = None,
) -> None:
    """Check local prerequisites and return failure when a required capability is missing."""
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, required: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "required": required, "detail": detail})

    resolved = workspace.resolve()
    check("Python 3.11+", sys.version_info >= (3, 11), True, sys.version.split()[0])
    check("Git", shutil.which("git") is not None, True, shutil.which("git") or "not found")
    check("Workspace", resolved.is_dir(), True, str(resolved))
    git_path = shutil.which("git")
    is_git = (
        subprocess.run(  # noqa: S603 - resolved executable and fixed arguments
            [git_path, "-C", str(resolved), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            check=False,
        ).returncode
        == 0
        if git_path and resolved.is_dir()
        else False
    )
    check("Git repository", is_git, False, "repository" if is_git else "not a Git repository")
    check(
        "Docker runner",
        shutil.which("docker") is not None,
        False,
        shutil.which("docker") or "not found",
    )
    check("Node.js", shutil.which("node") is not None, False, shutil.which("node") or "not found")
    try:
        settings = load_settings(resolved)
        settings.state_dir.mkdir(parents=True, exist_ok=True)
        writable = os.access(settings.state_dir, os.W_OK)
        check("Configuration", True, True, str(user_config_path()))
        check("State directory", writable, True, str(settings.state_dir))
        check("Model credential", bool(settings.llm_api_key), False, settings.llm_api_key_env)
        try:
            host = load_plugin_tree(
                workspace=resolved,
                trusted=is_workspace_trusted(resolved, settings),
                settings=settings,
            )
            check("Plugin tree", True, True, f"{len(host.plugins)} plugins")
        except PluginError as exc:
            check("Plugin tree", False, True, str(exc))
    except (OSError, ValueError) as exc:
        check("Configuration", False, True, str(exc))
    if api_url:
        try:
            response = httpx.get(api_url.rstrip("/") + "/health", timeout=3)
            check("Remote API", response.is_success, True, str(response.status_code))
        except httpx.HTTPError as exc:
            check("Remote API", False, True, str(exc))
    failed = [item for item in checks if item["required"] and not item["ok"]]
    if output_json:
        typer.echo(json.dumps({"ok": not failed, "checks": checks}, ensure_ascii=False))
    else:
        table = Table("Capability", "Status", "Required", "Detail", title="Zhixiao environment")
        for item in checks:
            table.add_row(
                str(item["name"]),
                "ok" if item["ok"] else "missing",
                "yes" if item["required"] else "no",
                str(item["detail"]),
            )
        Console().print(table)
    if failed:
        raise typer.Exit(EXIT_TASK_FAILED)


@app.command("version")
def version_command() -> None:
    """Print the CLI version and protocol schema version."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        current = version("zhixiao-agent")
    except PackageNotFoundError:
        current = "development"
    typer.echo(f"zhixiao {current} (protocol {SCHEMA_VERSION})")


if __name__ == "__main__":
    app()
