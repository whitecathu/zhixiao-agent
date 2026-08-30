from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from collections.abc import Awaitable, Callable, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any

import typer

from .cli_state import RunManifest, SessionStore, result_payload
from .hook_runtime import HookedToolRegistry, HookFailure, run_hooks
from .mcp_runtime import mcp_metadata
from .model import CodingModel, FallbackModel, ModelProfile, OpenAICompatibleModel
from .plugin import PluginHost, load_plugin_tree
from .runtime import AgentRuntime, RuntimeConfig
from .settings import AgentSettings
from .types import ModelTurn, PermissionMode, RunBudget

SCHEMA_VERSION = "1.1"


class WorkMode(StrEnum):
    ASK = "ask"
    PLAN = "plan"
    CODE = "code"
    REVIEW = "review"


class ApprovalPolicy(StrEnum):
    ON_REQUEST = "on_request"
    NEVER = "never"


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


def control_path(state_dir: Path, run_id: str) -> Path:
    """Return {state_dir}/control/{run_id} cooperative-stop file."""
    return Path(state_dir).expanduser().resolve() / "control" / run_id


def build_model(settings: AgentSettings, *, offline: bool) -> CodingModel:
    if offline:
        return OfflineModel()
    if not settings.llm_api_key:
        raise typer.BadParameter(
            f"{settings.llm_api_key_env} is required unless --offline is used"
        )
    model: CodingModel = OpenAICompatibleModel(
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
    return model


def _runtime_config(**values: Any) -> RuntimeConfig:
    """Build against both the previous and upgraded RuntimeConfig contracts."""
    accepted = {field.name for field in inspect.signature(RuntimeConfig).parameters.values()}
    return RuntimeConfig(**{key: value for key, value in values.items() if key in accepted})


async def _ignore_event(event: dict[str, Any]) -> None:
    del event


def _custom_command_context(
    prompt: str,
    host: PluginHost,
    mode: WorkMode,
) -> tuple[str, WorkMode, tuple[str, ...]]:
    if not prompt.startswith("/"):
        return prompt, mode, ()
    invocation, _, arguments = prompt[1:].partition(" ")
    contribution = host.commands.get(invocation) or host.commands.get(invocation.lower())
    if contribution is None or contribution.template is None:
        return prompt, mode, ()
    effective_mode = mode
    try:
        if contribution.mode:
            effective_mode = WorkMode(contribution.mode)
    except ValueError:
        pass
    return contribution.expand(arguments), effective_mode, contribution.tools


def local_runtime_bundle(
    *,
    settings: AgentSettings,
    workspace: Path,
    permission: PermissionMode,
    mode: WorkMode,
    approval_policy: ApprovalPolicy,
    approved: bool,
    approve_ops: frozenset[str],
    network: frozenset[str],
    offline: bool,
    runner: str,
    test_command: str | None,
    budget: RunBudget,
    allow_unverified: str | None,
    trusted: bool,
    command_timeout: int,
    on_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    command_tools: Sequence[str] = (),
    plugin_host: PluginHost | None = None,
) -> tuple[AgentRuntime, RuntimeConfig, dict[str, list[str]]]:
    host = plugin_host or load_plugin_tree(
        workspace=workspace,
        trusted=trusted,
        settings=settings,
        include_experimental=bool(approve_ops & {"mcp"}),
    )
    hooks = {name: list(commands) for name, commands in host.hooks.items()}
    registry: Any = host.tools
    if hooks:
        registry = HookedToolRegistry(
            registry,
            hooks=hooks,
            workspace=workspace,
            trusted=trusted,
            permission=permission,
            timeout=command_timeout,
        )
    tool_metadata: dict[str, Any] = {
        "mode": mode.value,
        "trusted_workspace": trusted,
        "plugins": [plugin.name for plugin in host.plugins],
    }
    if command_tools:
        tool_metadata["command_tools"] = list(command_tools)
    if "mcp" in approve_ops and host.mcp_servers:
        tool_metadata.update(
            mcp_metadata(
                host.mcp_servers,
                workspace=workspace,
                network_approved="mcp" in network,
            )
        )
    runtime = AgentRuntime(build_model(settings, offline=offline), registry=registry)
    config = _runtime_config(
        permission=permission,
        runner_backend=runner,
        max_tool_iterations=min(budget.max_tool_calls, budget.max_model_turns),
        budget=budget,
        command_timeout=command_timeout,
        require_plan_approval=approval_policy is ApprovalPolicy.ON_REQUEST,
        approved=approved,
        ops_approved=bool(approve_ops),
        ops_capabilities=approve_ops,
        network_approved=bool(network),
        network_capabilities=network,
        test_command=test_command,
        on_event=on_event,
        tool_metadata=tool_metadata,
        skills_roots=tuple(host.skill_roots),
        allow_unverified=allow_unverified,
        mode=mode.value,
        plugin_prompt=host.render_prompt(),
        state_dir=settings.state_dir,
    )
    return runtime, config, hooks


async def execute_local(
    prompt: str,
    *,
    workspace: Path,
    settings: AgentSettings,
    permission: PermissionMode,
    mode: WorkMode,
    approval_policy: ApprovalPolicy,
    approved: bool,
    approve_ops: frozenset[str],
    network: frozenset[str],
    offline: bool,
    runner: str,
    test_command: str | None,
    max_model_rounds: int,
    max_tool_calls: int,
    max_tokens: int | None,
    max_cost_usd: float | None,
    allow_unverified: str | None,
    trusted: bool,
    on_event: Callable[[dict[str, Any]], Awaitable[None]],
    command_timeout: int | None = None,
    run_id: str | None = None,
    parent_run_id: str | None = None,
) -> dict[str, Any]:
    host = load_plugin_tree(
        workspace=workspace,
        trusted=trusted,
        settings=settings,
        include_experimental=bool(approve_ops & {"mcp"}),
    )
    prompt, mode, command_tools = _custom_command_context(prompt, host, mode)
    identifier = run_id or uuid.uuid4().hex
    store = SessionStore(settings.state_dir)
    effective_timeout = command_timeout or settings.command_timeout_seconds
    budget = RunBudget(
        max_model_turns=max_model_rounds,
        max_tool_calls=max_tool_calls,
        max_tokens=max_tokens or 200_000,
        max_cost_usd=max_cost_usd,
        max_duration_seconds=max(int(effective_timeout), 1),
    )
    manifest = RunManifest(
        schema_version=SCHEMA_VERSION,
        run_id=identifier,
        prompt=prompt,
        workspace=str(workspace),
        status="pending",
        mode=mode.value,
        permission=permission.value,
        runner=runner,
        approval_policy=approval_policy.value,
        budget=budget.model_dump(mode="json"),
        allow_unverified=allow_unverified,
        verification_commands=[test_command] if test_command else [],
        command_timeout=effective_timeout,
        ops_capabilities=sorted(approve_ops),
        network_capabilities=sorted(network),
        trusted_workspace=trusted,
        parent_run_id=parent_run_id,
    )
    store.save(manifest)
    runtime, config, hooks = local_runtime_bundle(
        settings=settings,
        workspace=workspace,
        permission=permission,
        mode=mode,
        approval_policy=approval_policy,
        approved=approved,
        approve_ops=approve_ops,
        network=network,
        offline=offline,
        runner=runner,
        test_command=test_command,
        budget=budget,
        allow_unverified=allow_unverified,
        trusted=trusted,
        command_timeout=effective_timeout,
        on_event=on_event,
        command_tools=command_tools,
        plugin_host=host,
    )
    hooks_deferred_for_approval = (
        permission is not PermissionMode.READ_ONLY
        and approval_policy is ApprovalPolicy.ON_REQUEST
        and not approved
    )
    try:
        if not hooks_deferred_for_approval:
            await run_hooks(
                "before_run",
                hooks.get("before_run", []),
                workspace=workspace,
                trusted=trusted,
                permission=permission,
                timeout=effective_timeout,
            )
        result = await runtime.run(prompt, workspace, config, run_id=identifier)
        payload = result_payload(result)
        if not hooks_deferred_for_approval and str(payload.get("status")) not in {
            "awaiting_approval",
            "blocked",
        }:
            await run_hooks(
                "after_verification",
                hooks.get("after_verification", []),
                workspace=workspace,
                trusted=trusted,
                permission=permission,
                timeout=effective_timeout,
            )
            await run_hooks(
                "after_run",
                hooks.get("after_run", []),
                workspace=workspace,
                trusted=trusted,
                permission=permission,
                timeout=effective_timeout,
            )
    except HookFailure as exc:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": identifier,
            "status": "failed",
            "summary": exc.execution.summary,
            "termination_reason": "hook_failed",
            "next_actions": ["fix or disable the failing workspace hook"],
            "hook": exc.execution.__dict__,
        }
    except BaseException as exc:
        manifest.status = "interrupted" if isinstance(exc, asyncio.CancelledError) else "failed"
        store.save(manifest)
        raise
    manifest.status = str(payload.get("status", "failed"))
    manifest.result = payload
    store.save(manifest)
    return payload


async def resume_local(
    run_id: str,
    *,
    settings: AgentSettings,
    approved: bool,
    offline: bool,
    on_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    store = SessionStore(settings.state_dir)
    manifest = store.get(run_id)
    if manifest is None:
        raise ValueError(f"local run not found: {run_id}")
    workspace = Path(manifest.workspace)
    budget = RunBudget.model_validate(manifest.budget or {})
    runtime, config, hooks = local_runtime_bundle(
        settings=settings,
        workspace=workspace,
        permission=PermissionMode(manifest.permission),
        mode=WorkMode(manifest.mode),
        approval_policy=ApprovalPolicy(manifest.approval_policy),
        approved=approved,
        approve_ops=frozenset(manifest.ops_capabilities),
        network=frozenset(manifest.network_capabilities),
        offline=offline,
        runner=manifest.runner,
        test_command=(
            manifest.verification_commands[0] if manifest.verification_commands else None
        ),
        allow_unverified=manifest.allow_unverified,
        budget=budget,
        trusted=manifest.trusted_workspace,
        command_timeout=manifest.command_timeout,
        on_event=on_event,
    )
    try:
        if approved:
            await run_hooks(
                "before_run",
                hooks.get("before_run", []),
                workspace=workspace,
                trusted=manifest.trusted_workspace,
                permission=PermissionMode(manifest.permission),
                timeout=manifest.command_timeout,
            )
        result = await runtime.resume(run_id, approved=approved, config=config)
        payload = result_payload(result)
        if approved and str(payload.get("status")) not in {
            "awaiting_approval",
            "blocked",
            "interrupted",
        }:
            await run_hooks(
                "after_verification",
                hooks.get("after_verification", []),
                workspace=workspace,
                trusted=manifest.trusted_workspace,
                permission=PermissionMode(manifest.permission),
                timeout=manifest.command_timeout,
            )
            await run_hooks(
                "after_run",
                hooks.get("after_run", []),
                workspace=workspace,
                trusted=manifest.trusted_workspace,
                permission=PermissionMode(manifest.permission),
                timeout=manifest.command_timeout,
            )
    except HookFailure as exc:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "status": "failed",
            "summary": exc.execution.summary,
            "termination_reason": "hook_failed",
            "next_actions": ["fix or disable the failing workspace hook"],
            "hook": exc.execution.__dict__,
        }
    manifest.status = str(payload.get("status", "failed"))
    manifest.result = payload
    store.save(manifest)
    return payload


async def fork_local(
    run_id: str,
    *,
    settings: AgentSettings,
    prompt: str | None = None,
    offline: bool = False,
    on_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    parent = SessionStore(settings.state_dir).get(run_id)
    if parent is None:
        raise ValueError(f"local run not found: {run_id}")
    return await execute_local(
        prompt or parent.prompt,
        workspace=Path(parent.workspace),
        settings=settings,
        permission=PermissionMode(parent.permission),
        mode=WorkMode(parent.mode),
        approval_policy=ApprovalPolicy(parent.approval_policy),
        approved=False,
        approve_ops=frozenset(parent.ops_capabilities),
        network=frozenset(parent.network_capabilities),
        offline=offline,
        runner=parent.runner,
        test_command=(
            parent.verification_commands[0] if parent.verification_commands else None
        ),
        max_model_rounds=int(parent.budget.get("max_model_turns", 30)),
        max_tool_calls=int(parent.budget.get("max_tool_calls", 50)),
        max_tokens=int(parent.budget.get("max_tokens", 200_000)),
        max_cost_usd=parent.budget.get("max_cost_usd"),
        allow_unverified=parent.allow_unverified,
        trusted=parent.trusted_workspace,
        on_event=on_event or _ignore_event,
        command_timeout=parent.command_timeout,
        parent_run_id=run_id,
    )


def interrupt_local(run_id: str, *, settings: AgentSettings) -> dict[str, Any]:
    store = SessionStore(settings.state_dir)
    manifest = store.get(run_id)
    if manifest is None:
        raise ValueError(f"local run not found: {run_id}")
    stop_file = control_path(settings.state_dir, run_id)
    stop_file.parent.mkdir(parents=True, exist_ok=True)
    stop_file.write_text("interrupt\n", encoding="utf-8")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "status": "interrupted",
        "summary": "run interrupted",
        "termination_reason": "interrupted",
        "next_actions": [f"zhixiao resume {run_id}"],
    }
    manifest.status = "interrupted"
    manifest.result = payload
    store.save(manifest)
    return payload
