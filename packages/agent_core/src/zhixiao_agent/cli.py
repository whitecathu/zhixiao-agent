from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any, cast

import httpx
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .model import CodingModel, FallbackModel, ModelProfile, OpenAICompatibleModel
from .runtime import AgentRuntime, RuntimeConfig
from .settings import get_settings
from .types import ModelTurn, PermissionMode


class OfflineModel(CodingModel):
    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelTurn:
        self.calls += 1
        if self.calls == 1:
            return ModelTurn(
                content=json.dumps(
                    {
                        "plan": [
                            "Inspect project instructions and repository structure",
                            "Identify files relevant to the request",
                            "Run verification permitted by the selected mode",
                        ]
                    },
                    ensure_ascii=False,
                ),
                model="offline",
            )
        return ModelTurn(
            content=(
                "Offline mode completed repository discovery. "
                "Configure an API key for code changes."
            ),
            model="offline",
        )


console = Console()
app = typer.Typer(
    name="zhixiao",
    help="Auditable AI full-stack engineering agent.",
    no_args_is_help=False,
    invoke_without_command=True,
)


@app.callback()
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        from .tui import launch

        launch()


@app.command()
def run(
    prompt: Annotated[str, typer.Option("--prompt", "-p", help="Engineering task")],
    workspace: Annotated[Path, typer.Option("--workspace", "-w")] = Path("."),
    permission: Annotated[PermissionMode, typer.Option("--permission")] = PermissionMode.READ_ONLY,
    runner: Annotated[str, typer.Option("--runner")] = "local",
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Approve the generated plan")] = False,
    offline: Annotated[
        bool, typer.Option("--offline", help="Do not call an external model")
    ] = False,
    output_json: Annotated[
        bool, typer.Option("--json", help="Print machine-readable result")
    ] = False,
    test_command: Annotated[str | None, typer.Option("--test-command")] = None,
    api_url: Annotated[
        str | None, typer.Option("--api-url", envvar="ZHIXIAO_API_URL", help="Remote API URL")
    ] = None,
    api_token: Annotated[
        str | None,
        typer.Option("--api-token", envvar="ZHIXIAO_API_TOKEN", help="Remote bearer token"),
    ] = None,
    space_id: Annotated[int, typer.Option("--space-id", envvar="ZHIXIAO_SPACE_ID")] = 1,
    repository_id: Annotated[int | None, typer.Option("--repository-id")] = None,
) -> None:
    """Run one task locally; non-zero exit means the task failed or awaits approval."""
    if api_url:
        if repository_id is None:
            raise typer.BadParameter("--repository-id is required with --api-url")
        remote = asyncio.run(
            _run_remote(
                api_url,
                prompt=prompt,
                permission=permission,
                repository_id=repository_id,
                token=api_token,
                space_id=space_id,
                approve=yes,
            )
        )
        if output_json:
            console.print_json(json.dumps(remote, ensure_ascii=False, default=str))
        else:
            console.print(
                Panel(
                    f"[bold]{remote.get('status', 'unknown')}[/bold]\n"
                    f"{remote.get('title', prompt)}",
                    title="Zhixiao Remote",
                )
            )
        status = str(remote.get("status", "failed"))
        if status not in {"succeeded", "completed"}:
            raise typer.Exit(code=2 if status == "awaiting_approval" else 1)
        return
    resolved = workspace.resolve()
    if not resolved.is_dir():
        raise typer.BadParameter(f"workspace is not a directory: {resolved}")
    settings = get_settings()
    if offline:
        model: CodingModel = OfflineModel()
    else:
        if not settings.llm_api_key:
            raise typer.BadParameter("LLM_API_KEY is required unless --offline is used")
        model = OpenAICompatibleModel(
            ModelProfile(
                provider=settings.llm_provider,
                model=settings.llm_model,
                api_base=settings.llm_api_base,
                api_key=settings.llm_api_key,
            )
        )
        if settings.llm_fallback_api_key and settings.llm_fallback_model:
            model = FallbackModel(
                model,
                OpenAICompatibleModel(
                    ModelProfile(
                        provider=settings.llm_fallback_provider or "fallback",
                        model=settings.llm_fallback_model,
                        api_base=settings.llm_fallback_api_base,
                        api_key=settings.llm_fallback_api_key,
                    )
                ),
            )
    runtime = AgentRuntime(model)
    result = asyncio.run(
        runtime.run(
            prompt,
            resolved,
            RuntimeConfig(
                permission=permission,
                runner_backend=runner,
                approved=yes,
                require_plan_approval=True,
                test_command=test_command,
                command_timeout=settings.command_timeout_seconds,
            ),
        )
    )
    if output_json:
        console.print_json(result.model_dump_json())
    else:
        _render_result(result.model_dump(mode="json"))
    if result.status.value not in {"succeeded"}:
        raise typer.Exit(code=2 if result.status.value == "awaiting_approval" else 1)


@app.command()
def doctor() -> None:
    """Check local runtime prerequisites without changing the system."""
    import shutil
    import sys

    table = Table(title="Zhixiao environment")
    table.add_column("Capability")
    table.add_column("Status")
    table.add_row("Python 3.11+", "ok" if sys.version_info >= (3, 11) else "missing")
    table.add_row("Git", "ok" if shutil.which("git") else "missing")
    table.add_row("Docker runner", "ok" if shutil.which("docker") else "optional / unavailable")
    table.add_row("Node.js", "ok" if shutil.which("node") else "optional / unavailable")
    console.print(table)


def _render_result(result: dict[str, Any]) -> None:
    console.print(Panel(f"[bold]{result['status']}[/bold]\n{result['summary']}", title="Zhixiao"))
    if result.get("plan"):
        console.print("\n[bold]Plan[/bold]")
        for index, step in enumerate(result["plan"], 1):
            console.print(f"  {index}. {step}")
    if result.get("test_command"):
        verification = result.get("test_exit_code")
        console.print(f"\n[bold]Verification[/bold] {result['test_command']} -> {verification}")
    if result.get("diff"):
        console.print(Panel(result["diff"], title="Git diff"))


async def _run_remote(
    api_url: str,
    *,
    prompt: str,
    permission: PermissionMode,
    repository_id: int,
    token: str | None,
    space_id: int,
    approve: bool,
) -> dict[str, Any]:
    base = api_url.rstrip("/") + "/api/v1"
    headers = {"X-Space-Id": str(space_id)}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    timeout = httpx.Timeout(30, read=None)
    async with httpx.AsyncClient(headers=headers, timeout=timeout) as client:
        response = await client.post(
            f"{base}/task-runs",
            json={
                "repository_id": repository_id,
                "title": prompt.strip().splitlines()[0][:255],
                "prompt": prompt,
                "permission_mode": permission.value,
            },
        )
        response.raise_for_status()
        run = cast(dict[str, Any], _api_data(response))
        run_id = int(run["id"])
        if run.get("status") == "awaiting_approval" and not approve:
            return run
        if run.get("status") == "awaiting_approval":
            approvals_response = await client.get(f"{base}/task-runs/{run_id}/approvals")
            approvals_response.raise_for_status()
            approvals = _api_data(approvals_response)
            pending = next(item for item in approvals if item["status"] == "pending")
            decision = await client.post(
                f"{base}/approvals/{pending['id']}/decision",
                json={"decision": "approved"},
            )
            decision.raise_for_status()
        async with client.stream("GET", f"{base}/task-runs/{run_id}/events") as stream:
            stream.raise_for_status()
            event_name = "message"
            async for line in stream.aiter_lines():
                if line.startswith("event:"):
                    event_name = line.removeprefix("event:").strip()
                elif line.startswith("data:"):
                    data = json.loads(line.removeprefix("data:").strip())
                    if event_name in {"run.finished", "run_finished", "run.failed", "error"}:
                        break
                    if data.get("status") in {"succeeded", "failed", "cancelled"}:
                        break
        final_response = await client.get(f"{base}/task-runs/{run_id}")
        final_response.raise_for_status()
        return cast(dict[str, Any], _api_data(final_response))


def _api_data(response: httpx.Response) -> Any:
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise RuntimeError(f"remote API returned an invalid envelope: {payload}")
    return payload.get("data")


if __name__ == "__main__":
    app()
