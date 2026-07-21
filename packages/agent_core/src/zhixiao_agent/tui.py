from __future__ import annotations

from typing import Any


def launch() -> None:
    try:
        from textual.app import App, ComposeResult
        from textual.containers import Vertical
        from textual.widgets import Footer, Header, Input, RichLog, Static
    except ImportError as exc:
        raise RuntimeError("Install zhixiao-agent[cli] to use the TUI") from exc

    class ZhixiaoApp(App[None]):
        TITLE = "Zhixiao Agent"
        SUB_TITLE = "Plan, implement, verify"
        BINDINGS = [("ctrl+q", "quit", "Quit")]

        def __init__(self) -> None:
            super().__init__()
            from .cli import OfflineModel
            from .model import ModelProfile, OpenAICompatibleModel
            from .runtime import AgentRuntime
            from .settings import get_settings

            settings = get_settings()
            model = (
                OpenAICompatibleModel(
                    ModelProfile(
                        provider=settings.llm_provider,
                        model=settings.llm_model,
                        api_base=settings.llm_api_base,
                        api_key=settings.llm_api_key,
                    )
                )
                if settings.llm_api_key
                else OfflineModel()
            )
            self.runtime = AgentRuntime(model)
            self.permission = PermissionMode.READ_ONLY
            self.pending_run_id: str | None = None

        def compose(self) -> ComposeResult:
            yield Header()
            with Vertical():
                yield Static(
                    "Enter a task. Commands: /mode read_only|edit|execute|full, /approve, /deny.",
                    id="help",
                )
                yield RichLog(id="log", wrap=True, markup=True)
                yield Input(placeholder="Describe a software engineering task…", id="prompt")
            yield Footer()

        async def on_input_submitted(self, event: Input.Submitted) -> None:
            from pathlib import Path

            from .runtime import RuntimeConfig

            log = self.query_one("#log", RichLog)
            prompt = event.value.strip()
            if not prompt:
                return
            event.input.value = ""
            if prompt.startswith("/mode "):
                try:
                    self.permission = PermissionMode(prompt.split(maxsplit=1)[1])
                    log.write(f"Permission mode: [bold]{self.permission.value}[/bold]")
                except ValueError:
                    log.write("[red]Unknown permission mode.[/red]")
                return
            if prompt in {"/approve", "/deny"}:
                if not self.pending_run_id:
                    log.write("[yellow]There is no run awaiting approval.[/yellow]")
                    return
                result = await self.runtime.resume(
                    self.pending_run_id,
                    approved=prompt == "/approve",
                    config=RuntimeConfig(permission=self.permission),
                )
                self.pending_run_id = None
                self._render(log, result)
                return
            log.write(f"[bold]You[/bold] {prompt}")
            result = await self.runtime.run(
                prompt,
                Path.cwd(),
                RuntimeConfig(permission=self.permission, require_plan_approval=True),
            )
            if result.status.value == "awaiting_approval":
                self.pending_run_id = result.run_id
            self._render(log, result)

        @staticmethod
        def _render(log: Any, result: Any) -> None:
            log.write(f"[bold green]Zhixiao[/bold green] {result.summary}")
            log.write(f"Status: [bold]{result.status.value}[/bold]")
            for index, step in enumerate(result.plan, 1):
                log.write(f"  {index}. {step}")
            if result.status.value == "awaiting_approval":
                log.write("[yellow]Review the plan, then enter /approve or /deny.[/yellow]")

    from .types import PermissionMode

    ZhixiaoApp().run()
