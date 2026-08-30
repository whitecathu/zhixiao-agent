from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .plugin import PluginError, load_plugin_tree
from .session_controller import (
    ApprovalPolicy,
    WorkMode,
    execute_local,
    fork_local,
    interrupt_local,
    resume_local,
)
from .settings import is_workspace_trusted, load_settings
from .slash import SlashContext, SlashResult, dispatch_slash
from .types import PermissionMode

DEFAULT_PLACEHOLDER = "Describe a software engineering task…"
APPROVAL_PLACEHOLDER = "Type /approve or /deny"


def create_app(
    initial_prompt: str | None = None,
    workspace: Path | None = None,
    offline: bool = False,
    permission: PermissionMode = PermissionMode.READ_ONLY,
    mode: WorkMode = WorkMode.ASK,
    trust_workspace: bool = False,
    **kwargs: Any,
) -> Any:
    """Build the Textual app separately so pilot tests do not enter the terminal loop."""
    del kwargs
    try:
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical
        from textual.widgets import Footer, Header, Input, RichLog, Static
    except ImportError as exc:
        raise RuntimeError("Install zhixiao-agent[cli] to use the TUI") from exc

    class ZhixiaoApp(App[None]):
        TITLE = "Zhixiao Agent"
        SUB_TITLE = "Plan, implement, verify"
        CSS = """
        #status { height: 1; padding: 0 1; color: $text-muted; }
        #body { height: 1fr; }
        #log { width: 1fr; height: 1fr; }
        #dock { width: 32; height: 1fr; padding: 0 1; }
        """
        BINDINGS = [("ctrl+q", "quit", "Quit"), ("ctrl+c", "cancel", "Cancel run")]

        def __init__(
            self,
            first_prompt: str | None = None,
            *,
            workspace: Path | None = None,
            offline: bool = False,
            permission: PermissionMode = PermissionMode.READ_ONLY,
            mode: WorkMode = WorkMode.ASK,
            trust_workspace: bool = False,
        ) -> None:
            super().__init__()
            resolved = (workspace or Path.cwd()).expanduser().resolve()
            self.workspace = resolved
            self.settings = load_settings(resolved, trusted_workspace=trust_workspace)
            self.trusted = bool(trust_workspace) or is_workspace_trusted(
                resolved, self.settings
            )
            self.offline = bool(offline) or not bool(self.settings.llm_api_key)
            self.permission = permission
            self.mode = mode
            self.approval_policy = ApprovalPolicy.ON_REQUEST
            self.pending_run_id: str | None = None
            self.last_result: Any | None = None
            self.last_run_id: str | None = None
            self.current_run_id: str | None = None
            self.first_prompt = first_prompt
            self.active_worker: Any | None = None
            self.queued_prompt: str | None = None
            self.model_label = f"{self.settings.llm_provider}/{self.settings.llm_model}"
            self.plugin_host = load_plugin_tree(
                workspace=resolved,
                trusted=self.trusted,
                settings=self.settings,
            )
            self.execute_local: Callable[..., Awaitable[Any]] = execute_local
            self.resume_local: Callable[..., Awaitable[Any]] = resume_local
            self.fork_local: Callable[..., Awaitable[Any]] = fork_local
            self.interrupt_local: Callable[..., Any] = interrupt_local

        def compose(self) -> ComposeResult:
            yield Header()
            with Vertical():
                yield Static(self._status_text(), id="status")
                with Horizontal(id="body"):
                    yield RichLog(id="log", wrap=True, markup=True)
                    yield Static("", id="dock")
                yield Input(placeholder=DEFAULT_PLACEHOLDER, id="prompt")
            yield Footer()

        def on_mount(self) -> None:
            self._refresh_chrome()
            if self.first_prompt:
                prompt = self.first_prompt
                self.first_prompt = None
                self.call_after_refresh(self._start_run, prompt)

        async def on_input_submitted(self, event: Input.Submitted) -> None:
            prompt = event.value.strip()
            if not prompt:
                return
            event.input.value = ""
            if prompt[:1] == "/":
                await self._command(prompt)
                return
            if self._busy():
                self._queue_prompt(prompt)
                return
            self._start_run(prompt)

        def _slash_context(self) -> SlashContext:
            return SlashContext(
                workspace=self.workspace,
                permission=self.permission,
                mode=self.mode,
                trusted=self.trusted,
                settings=self.settings,
                pending_run_id=self.pending_run_id,
                last_result=self.last_result,
                last_run_id=self.last_run_id,
                busy=self._busy(),
                model_label=self.model_label,
                host=self.plugin_host,
            )

        async def _command(self, raw: str) -> None:
            await self._apply_slash(dispatch_slash(raw, self._slash_context()))

        async def _apply_slash(self, result: SlashResult) -> None:
            log = self.query_one("#log", RichLog)
            if result.kind == "error":
                log.write(f"[red]{result.message}[/red]")
                return
            if result.kind == "cancel":
                self.action_cancel()
                return
            if result.kind == "permission":
                log.write(result.message)
                if result.permission is not None:
                    self.permission = result.permission
                    self._refresh_chrome()
                return
            if result.kind == "mode":
                log.write(result.message)
                if result.mode is not None:
                    self.mode = result.mode
                    self._refresh_chrome()
                return
            if result.kind == "workspace":
                if result.workspace is None:
                    log.write(result.message)
                    return
                candidate = result.workspace.expanduser().resolve()
                if not candidate.is_dir():
                    log.write(f"[red]Not a directory: {candidate}[/red]")
                    return
                settings = load_settings(candidate, trusted_workspace=self.trusted)
                trusted = self.trusted or is_workspace_trusted(candidate, settings)
                try:
                    host = load_plugin_tree(
                        workspace=candidate,
                        trusted=trusted,
                        settings=settings,
                    )
                except PluginError as exc:
                    log.write(f"[red]plugin tree failed: {exc}[/red]")
                    return
                self.workspace = candidate
                self.settings = settings
                self.trusted = trusted
                self.plugin_host = host
                log.write(f"Workspace: [bold]{candidate}[/bold]")
                self._refresh_chrome()
                return
            if result.kind == "start_run" and result.prompt:
                if result.mode is not None:
                    self.mode = result.mode
                    self._refresh_chrome()
                self._start_run(result.prompt)
                return
            if result.kind == "steer" and result.prompt:
                if self._busy():
                    self._queue_prompt(result.prompt)
                    return
                self._start_run(result.prompt)
                return
            if result.kind == "queue" and result.prompt:
                self._queue_prompt(result.prompt)
                return
            if result.kind in {"approve", "deny", "resume"} and result.run_id:
                log.write(result.message)
                self._start_resume(
                    result.run_id, approved=bool(result.approved)
                )
                return
            if result.kind == "fork" and result.run_id:
                log.write(result.message)
                self._start_fork(result.run_id, prompt=result.prompt)
                return
            log.write(result.message)

        def _busy(self) -> bool:
            return self.active_worker is not None and not self.active_worker.is_finished

        def _queue_prompt(self, prompt: str) -> None:
            self.queued_prompt = prompt
            log = self.query_one("#log", RichLog)
            log.write(
                "[yellow]Queued next turn; it will start after the current run "
                "finishes.[/yellow]"
            )

        def _start_run(self, prompt: str) -> None:
            if self._busy():
                self._queue_prompt(prompt)
                return
            self._begin_run(prompt)

        def _begin_run(self, prompt: str) -> None:
            log = self.query_one("#log", RichLog)
            log.write(f"[bold]You[/bold] {prompt}")
            self.current_run_id = uuid.uuid4().hex
            self.last_run_id = self.current_run_id
            self._refresh_chrome()
            self.active_worker = self.run_worker(
                self._execute(prompt),
                name="agent-run",
                exclusive=True,
                exit_on_error=False,
            )

        def _start_resume(self, run_id: str, *, approved: bool) -> None:
            if self._busy():
                self.query_one("#log", RichLog).write(
                    "[yellow]A run is already active; use /cancel first.[/yellow]"
                )
                return
            self.current_run_id = run_id
            self.last_run_id = run_id
            self._refresh_chrome()
            self.active_worker = self.run_worker(
                self._resume(run_id, approved=approved),
                name="agent-run",
                exclusive=True,
                exit_on_error=False,
            )

        def _start_fork(self, run_id: str, *, prompt: str | None) -> None:
            if self._busy():
                self.query_one("#log", RichLog).write(
                    "[yellow]A run is already active; use /cancel first.[/yellow]"
                )
                return
            self.current_run_id = uuid.uuid4().hex
            self.last_run_id = self.current_run_id
            self._refresh_chrome()
            self.active_worker = self.run_worker(
                self._fork(run_id, prompt=prompt),
                name="agent-run",
                exclusive=True,
                exit_on_error=False,
            )

        async def _execute(self, prompt: str) -> None:
            await self._run_session(lambda on_event: self._call_execute(prompt, on_event))

        async def _resume(self, run_id: str, *, approved: bool) -> None:
            async def invoke(on_event: Callable[[dict[str, Any]], Awaitable[None]]) -> Any:
                return await self.resume_local(
                    run_id,
                    settings=self.settings,
                    approved=approved,
                    offline=self.offline,
                    on_event=on_event,
                )

            await self._run_session(invoke)

        async def _fork(self, run_id: str, *, prompt: str | None) -> None:
            async def invoke(on_event: Callable[[dict[str, Any]], Awaitable[None]]) -> Any:
                return await self.fork_local(
                    run_id,
                    settings=self.settings,
                    prompt=prompt,
                    offline=self.offline,
                    on_event=on_event,
                )

            await self._run_session(invoke)

        async def _call_execute(
            self,
            prompt: str,
            on_event: Callable[[dict[str, Any]], Awaitable[None]],
        ) -> Any:
            return await self.execute_local(
                prompt,
                workspace=self.workspace,
                settings=self.settings,
                permission=self.permission,
                mode=self.mode,
                approval_policy=self.approval_policy,
                approved=False,
                approve_ops=frozenset(),
                network=frozenset(),
                offline=self.offline,
                runner=self.settings.runner_backend,
                test_command=None,
                max_model_rounds=30,
                max_tool_calls=50,
                max_tokens=None,
                max_cost_usd=None,
                allow_unverified=None,
                trusted=self.trusted,
                on_event=on_event,
                run_id=self.current_run_id,
            )

        async def _run_session(
            self,
            invoke: Callable[
                [Callable[[dict[str, Any]], Awaitable[None]]], Awaitable[Any]
            ],
        ) -> None:
            log = self.query_one("#log", RichLog)
            cancelled = False

            async def on_event(event: dict[str, Any]) -> None:
                log.write(self._format_event(event))

            try:
                result = await invoke(on_event)
            except asyncio.CancelledError:
                cancelled = True
                raise
            except Exception as exc:  # noqa: BLE001 - TUI must survive task errors
                log.write(f"[red]Run failed: {exc}[/red]")
            else:
                self._store_result(result)
                self._render(log, result)
            finally:
                self.current_run_id = None
                if not cancelled:
                    self.call_after_refresh(self._drain_queue)

        def _store_result(self, result: Any) -> None:
            self.last_result = result
            run_id = _result_run_id(result) or self.current_run_id
            if run_id:
                self.last_run_id = run_id
            status = _result_status(result)
            if status == "awaiting_approval":
                self.pending_run_id = run_id
            else:
                self.pending_run_id = None
            self._refresh_placeholder()
            self._refresh_chrome()
            self._update_dock(result)

        @staticmethod
        def _format_event(event: dict[str, Any]) -> str:
            name = str(event.get("event", "message"))
            data = event.get("data") or {}
            if not isinstance(data, dict):
                data = {}
            summary = data.get("summary") or data.get("status") or data.get("node") or ""
            lowered = name.lower()
            if "diff" in lowered or data.get("diff"):
                tag = "diff"
            elif any(token in lowered for token in ("terminal", "command", "test")):
                tag = "term"
            else:
                tag = "tool"
            detail = f"{name}{': ' + str(summary) if summary else ''}"
            return f"[dim]\\[{tag}\\] {detail}[/dim]"

        def action_cancel(self) -> None:
            log = self.query_one("#log", RichLog)
            if self.active_worker is None or self.active_worker.is_finished:
                log.write("There is no active run.")
                return
            self.queued_prompt = None
            self.active_worker.cancel()
            run_id = self.current_run_id or self.last_run_id
            if run_id:
                try:
                    maybe = self.interrupt_local(run_id, settings=self.settings)
                    if inspect.isawaitable(maybe):
                        self.run_worker(maybe, name="interrupt", exit_on_error=False)
                except Exception as exc:  # noqa: BLE001 - cancel must still report recovery
                    log.write(f"[dim]interrupt marker skipped: {exc}[/dim]")
            log.write("[yellow]Run cancelled; the checkpoint remains recoverable.[/yellow]")

        def _render(self, log: Any, result: Any) -> None:
            summary = _result_field(result, "summary") or ""
            status = _result_status(result) or "unknown"
            log.write(f"[bold green]Zhixiao[/bold green] {summary}")
            log.write(f"Status: [bold]{status}[/bold]")
            plan = _result_plan(result)
            for index, step in enumerate(plan, 1):
                log.write(f"  {index}. {step}")
            if status == "awaiting_approval":
                log.write("[yellow]Review the plan, then enter /approve or /deny.[/yellow]")
            self._update_dock(result)
            self._refresh_placeholder()
            self._refresh_chrome()

        def _update_dock(self, result: Any) -> None:
            try:
                dock = self.query_one("#dock", Static)
            except Exception:  # noqa: BLE001 - dock is optional chrome
                return
            lines: list[str] = []
            plan = _result_plan(result)
            if plan:
                lines.append("[bold]Plan[/bold]")
                lines.extend(f"{index}. {step}" for index, step in enumerate(plan, 1))
            outcome = _verification_outcome(result)
            if outcome:
                lines.append(f"[bold]Verify[/bold] {outcome}")
            dock.update("\n".join(lines))

        def _status_text(self) -> str:
            run = self.current_run_id or self.last_run_id or "-"
            if self._busy():
                phase = "busy"
            else:
                phase = _result_status(self.last_result) or "idle"
            return (
                f"{self.workspace}  perm={self.permission.value}  "
                f"mode={self.mode.value}  model={self.model_label}  "
                f"run={run}  {phase}"
            )

        def _refresh_chrome(self) -> None:
            text = self._status_text()
            self.sub_title = text
            try:
                self.query_one("#status", Static).update(text)
            except Exception:  # noqa: BLE001 - compose may not have mounted yet
                return

        def _refresh_placeholder(self) -> None:
            try:
                prompt = self.query_one("#prompt", Input)
            except Exception:  # noqa: BLE001 - compose may not have mounted yet
                return
            waiting = bool(self.pending_run_id) or _result_status(self.last_result) == (
                "awaiting_approval"
            )
            prompt.placeholder = APPROVAL_PLACEHOLDER if waiting else DEFAULT_PLACEHOLDER

        def _drain_queue(self) -> None:
            queued = self.queued_prompt
            self.queued_prompt = None
            self._refresh_chrome()
            if queued:
                self._begin_run(queued)

    return ZhixiaoApp(
        initial_prompt,
        workspace=workspace,
        offline=offline,
        permission=permission,
        mode=mode,
        trust_workspace=trust_workspace,
    )


def launch(
    initial_prompt: str | None = None,
    workspace: Path | None = None,
    offline: bool = False,
    permission: PermissionMode = PermissionMode.READ_ONLY,
    mode: WorkMode = WorkMode.ASK,
    trust_workspace: bool = False,
    **kwargs: Any,
) -> None:
    create_app(
        initial_prompt=initial_prompt,
        workspace=workspace,
        offline=offline,
        permission=permission,
        mode=mode,
        trust_workspace=trust_workspace,
        **kwargs,
    ).run()


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
    return str(getattr(value, "value", value))


def _result_status(result: Any) -> str:
    return _enum_value(_result_field(result, "status"))


def _result_plan(result: Any) -> list[str]:
    plan = _result_field(result, "plan") or []
    if isinstance(plan, list):
        return [str(item) for item in plan]
    return []


def _verification_outcome(result: Any) -> str:
    verification = _result_field(result, "verification")
    if verification is None:
        return ""
    if isinstance(verification, dict):
        return str(verification.get("outcome", ""))
    return _enum_value(getattr(verification, "outcome", None))
