from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import os
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Hashable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict, cast

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .context_compact import maybe_compact_messages
from .instructions import discover_instructions, render_instructions
from .model import CodingModel
from .routing import classify_task, route_task, with_experimental_tools
from .runner import BubblewrapRunner, DockerRunner, LocalRunner, Runner
from .skills import SkillManager, default_skill_roots, render_skill_context
from .tools import ToolContext, ToolRegistry, build_default_registry
from .tools.git import WorktreeManager
from .tools.registry import READ_ONLY_TOOLS
from .types import (
    AgentEvent,
    Artifact,
    PermissionMode,
    RunBudget,
    RunResult,
    RunStatus,
    RunUsage,
    TaskType,
    TerminationReason,
    ToolStatus,
    VerificationOutcome,
    VerificationResult,
    VerificationStage,
)
from .workflow import WorkflowDefinition, WorkflowNode

_MAX_EVENTS_IN_STATE = 40
_MAX_TOOL_RESULT_CHARS = 4_000
EventSink = Callable[[dict[str, Any]], Awaitable[None]]


class AgentState(TypedDict, total=False):
    run_id: str
    prompt: str
    workspace: str
    permission: str
    task_type: str
    allowed_tools: list[str]
    agents: list[str]
    project_context: str
    messages: list[dict[str, Any]]
    plan: list[str]
    events: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    status: str
    summary: str
    iterations: int
    repair_rounds: int
    test_command: str | None
    test_exit_code: int | None
    diff: str
    error: str | None
    approved: bool
    ops_approved: bool
    ops_capabilities: list[str]
    network_approved: bool
    network_capabilities: list[str]
    require_plan_approval: bool
    mode: str
    _had_tool_calls: bool
    source_workspace: str
    route_allowed_tools: list[str]
    workflow_node: str
    approved_nodes: list[str]
    approval_id: str
    verification: dict[str, Any]
    termination_reason: str | None
    usage: dict[str, Any]
    budgets: dict[str, Any]
    next_actions: list[str]
    started_at: float
    mutated: bool
    failure_counts: dict[str, int]
    last_tool_signatures: list[str]


@dataclass(frozen=True)
class RuntimeConfig:
    permission: PermissionMode = PermissionMode.READ_ONLY
    runner_backend: str = "local"
    max_tool_iterations: int = 20
    max_repair_rounds: int = 2
    command_timeout: int = 120
    require_plan_approval: bool = True
    approved: bool = False
    ops_approved: bool = False
    ops_capabilities: frozenset[str] = frozenset()
    network_approved: bool = False
    network_capabilities: frozenset[str] = frozenset()
    test_command: str | None = None
    docker_image: str = "python:3.11-slim"
    isolate_worktree: bool = True
    workflow_definition: dict[str, Any] | None = None
    workflow_version: int | None = None
    on_event: EventSink | None = None
    tool_metadata: dict[str, Any] | None = None
    skills_roots: tuple[Path, ...] | None = None
    budget: RunBudget = field(default_factory=RunBudget)
    allow_unverified: str | None = None
    verification_commands: tuple[str, ...] = ()
    mode: str = "code"
    plugin_prompt: str = ""
    state_dir: Path | None = None


_SYSTEM_PROMPT = """You are Zhixiao, an auditable software-engineering agent.
Work only inside the supplied workspace. Obey project instructions and permission boundaries.
Use tools to inspect facts before changing code. Keep changes scoped to the request.
When knowledge_search returns hits, cite evidence ids/paths; if degraded, say evidence is missing.
Never claim completion before verification. Return a concise final summary when no tool is needed.
Tool errors include recovery guidance; diagnose before retrying and stop after repeated root causes.
"""


class AgentRuntime:
    def __init__(
        self,
        model: CodingModel,
        *,
        registry: ToolRegistry | None = None,
        checkpointer: Any | None = None,
    ):
        self.model = model
        self.registry = registry or build_default_registry()
        self.checkpointer = checkpointer
        state_root = Path(os.environ.get("ZHIXIAO_STATE_DIR", Path.home() / ".zhixiao")).resolve()
        state_root.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path = state_root / "checkpoints.sqlite3"

    @staticmethod
    def _emit(state: AgentState, event: str, data: dict[str, Any]) -> list[dict[str, Any]]:
        events = list(state.get("events", []))
        sequence = int(events[-1]["sequence"]) + 1 if events else 1
        events.append(
            AgentEvent(
                sequence=sequence,
                run_id=state["run_id"],
                event=event,
                data=data,
            ).model_dump(mode="json")
        )
        if len(events) > _MAX_EVENTS_IN_STATE:
            events = events[-_MAX_EVENTS_IN_STATE :]
        return events

    def _tool_context(
        self, workspace: Path, state: AgentState, config: RuntimeConfig
    ) -> ToolContext:
        return ToolContext(
            workspace=workspace,
            permission=PermissionMode(state["permission"]),
            runner=self._runner(workspace, config),
            approved=bool(state.get("approved", False)),
            ops_approved=bool(state.get("ops_approved", False)),
            ops_capabilities=frozenset(state.get("ops_capabilities", [])),
            network_approved=bool(state.get("network_approved", False)),
            network_capabilities=frozenset(state.get("network_capabilities", [])),
            metadata=dict(config.tool_metadata or {}),
        )

    def _runner(self, workspace: Path, config: RuntimeConfig) -> Runner:
        runner_network_enabled = "git_publish" in config.network_capabilities
        if config.runner_backend == "docker":
            return DockerRunner(
                workspace,
                image=config.docker_image,
                network="bridge" if runner_network_enabled else "none",
            )
        if config.runner_backend == "bubblewrap":
            return BubblewrapRunner(
                workspace,
                network_enabled=runner_network_enabled,
            )
        if config.runner_backend != "local":
            raise ValueError(f"unsupported runner backend: {config.runner_backend}")
        return LocalRunner(workspace)

    @staticmethod
    def _usage(state: AgentState, *, elapsed: bool = False) -> RunUsage:
        usage = RunUsage.model_validate(state.get("usage", {}))
        if elapsed:
            usage.elapsed_seconds = max(time.monotonic() - state.get("started_at", 0.0), 0.0)
        return usage

    @staticmethod
    def _budget_reason(state: AgentState) -> str | None:
        usage = AgentRuntime._usage(state, elapsed=True)
        budget = RunBudget.model_validate(state.get("budgets", {}))
        if usage.model_turns >= budget.max_model_turns:
            return f"model turn budget exhausted ({budget.max_model_turns})"
        if usage.tool_calls >= budget.max_tool_calls:
            return f"tool call budget exhausted ({budget.max_tool_calls})"
        if usage.prompt_tokens + usage.completion_tokens >= budget.max_tokens:
            return f"token budget exhausted ({budget.max_tokens})"
        if budget.max_cost_usd is not None and usage.cost_usd >= budget.max_cost_usd:
            return f"cost budget exhausted (${budget.max_cost_usd:.4f})"
        if usage.elapsed_seconds >= budget.max_duration_seconds:
            return f"duration budget exhausted ({budget.max_duration_seconds}s)"
        return None

    @staticmethod
    def _approval_id(state: AgentState, kind: str, node_id: str = "") -> str:
        suffix = f":{node_id}" if node_id else ""
        return f"{state['run_id']}:{kind}{suffix}"

    def _build_graph(self, config: RuntimeConfig, checkpointer: Any) -> Any:
        runtime = self

        async def intake(state: AgentState) -> AgentState:
            task_type = classify_task(state["prompt"])
            route = route_task(task_type)
            allowed = set(
                with_experimental_tools(
                    route.tools,
                    ops_capabilities=frozenset(state.get("ops_capabilities", [])),
                    include_mcp=runtime.registry.get("mcp") is not None,
                    include_sub_agent=runtime.registry.get("sub_agent") is not None,
                )
            )
            if (
                runtime.registry.get("open_pull_request") is not None
                and "git_publish" in state.get("ops_capabilities", [])
            ):
                allowed.add("open_pull_request")
            mode = _resolve_work_mode(config, state)
            require_plan_approval = bool(
                state.get("require_plan_approval", config.require_plan_approval)
            )
            if mode in {"ask", "review", "plan"}:
                allowed &= READ_ONLY_TOOLS
            command_tools = (config.tool_metadata or {}).get("command_tools")
            if isinstance(command_tools, (list, tuple, set, frozenset)) and command_tools:
                allowed &= {str(item) for item in command_tools if str(item).strip()}
            if (
                mode == "plan"
                and PermissionMode(state["permission"]) is not PermissionMode.READ_ONLY
            ):
                require_plan_approval = True
            sorted_allowed = sorted(allowed)
            return {
                **state,
                "mode": mode,
                "task_type": task_type.value,
                "allowed_tools": sorted_allowed,
                "route_allowed_tools": sorted_allowed,
                "require_plan_approval": require_plan_approval,
                "agents": list(route.agents),
                "status": RunStatus.PLANNING.value,
                "events": runtime._emit(
                    state,
                    "run_started",
                    {
                        "task_type": task_type.value,
                        "agents": list(route.agents),
                        "workflow_version": config.workflow_version,
                    },
                ),
            }

        async def discover(state: AgentState) -> AgentState:
            workspace = Path(state["workspace"])
            context = runtime._tool_context(workspace, state, config)
            listing = await runtime.registry.execute(
                "list_directory",
                {"path": ".", "recursive": False, "limit": 200},
                context,
                allowed=set(state["allowed_tools"]),
            )
            instructions = render_instructions(discover_instructions(workspace), workspace)
            skills = SkillManager(
                default_skill_roots(workspace, extra=config.skills_roots)
            )
            skills.load()
            skill_context = render_skill_context(state["prompt"], skills)
            project_context = (
                f"Project files:\n{json.dumps(listing.data, ensure_ascii=False)}\n\n"
                f"Project instructions:\n{instructions or '(none)'}"
            )
            if skill_context:
                project_context = f"{project_context}\n\n{skill_context}"
            plugin_prompt = config.plugin_prompt.strip()
            if plugin_prompt:
                project_context = f"{project_context}\n\n{plugin_prompt}"
            return {
                **state,
                "project_context": project_context,
                "events": runtime._emit(
                    state,
                    "repository_discovered",
                    {
                        "entries": len(listing.data or []),
                        "instruction_chars": len(instructions),
                        "skill_chars": len(skill_context),
                    },
                ),
            }

        async def plan(state: AgentState) -> AgentState:
            workspace = Path(state["workspace"])
            skills = SkillManager(
                default_skill_roots(workspace, extra=config.skills_roots)
            )
            skills.load()
            skill_context = render_skill_context(state["prompt"], skills)
            system_prompt = (
                f"{_SYSTEM_PROMPT}\n\n{skill_context}" if skill_context else _SYSTEM_PROMPT
            )
            if config.plugin_prompt.strip():
                system_prompt = f"{system_prompt}\n\n{config.plugin_prompt.strip()}"
            budget_reason = runtime._budget_reason(state)
            if budget_reason:
                return _budget_failure(runtime, state, budget_reason)
            try:
                response = await runtime.model.complete(
                    [
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": (
                                "Create a decision-complete implementation plan as JSON "
                                "with a 'plan' string array. "
                                "Do not call tools in this planning step.\n\n"
                                f"Request: {state['prompt']}\n\n{state['project_context']}"
                            ),
                        },
                    ]
                )
            except Exception as exc:
                return _model_failure(runtime, state, exc)
            usage = runtime._usage(state)
            usage.model_turns += 1
            usage.prompt_tokens += response.prompt_tokens
            usage.completion_tokens += response.completion_tokens
            usage.cost_usd += response.cost_usd
            steps: list[str]
            try:
                payload = json.loads(response.content)
                steps = [str(item) for item in payload["plan"] if str(item).strip()]
            except (json.JSONDecodeError, KeyError, TypeError):
                steps = [
                    "Inspect the relevant implementation and tests",
                    "Make the smallest complete change allowed by the permission mode",
                    "Run focused verification and review the resulting diff",
                ]
            updated: AgentState = {
                **state,
                "plan": steps,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            f"Request: {state['prompt']}\n\n{state['project_context']}\n\n"
                            f"Approved plan:\n"
                            + "\n".join(f"{i + 1}. {step}" for i, step in enumerate(steps))
                        ),
                    },
                ],
                "events": runtime._emit(state, "plan_created", {"plan": steps}),
                "usage": usage.model_dump(),
            }
            if (
                state["require_plan_approval"]
                and PermissionMode(state["permission"]) is not PermissionMode.READ_ONLY
                and not state["approved"]
            ):
                approval_id = runtime._approval_id(updated, "plan")
                updated["approval_id"] = approval_id
                updated["status"] = RunStatus.AWAITING_APPROVAL.value
                updated["termination_reason"] = TerminationReason.AWAITING_APPROVAL.value
                updated["events"] = runtime._emit(
                    updated,
                    "approval_required",
                    {"approval_id": approval_id, "kind": "plan", "node_id": None},
                )
            return updated

        def after_plan(state: AgentState) -> str:
            if state["status"] == RunStatus.FAILED.value:
                return "end"
            return "awaiting" if state["status"] == RunStatus.AWAITING_APPROVAL.value else "execute"

        async def awaiting(state: AgentState) -> AgentState:
            waiting: AgentState = {**state}
            decision = interrupt(
                {
                    "approval_id": state.get("approval_id") or runtime._approval_id(state, "plan"),
                    "kind": "plan",
                    "node_id": None,
                    "run_id": state["run_id"],
                    "plan": state.get("plan", []),
                }
            )
            approved = bool(
                decision.get("approved", False) if isinstance(decision, dict) else decision
            )
            return {
                **waiting,
                "approved": approved,
                "status": (RunStatus.RUNNING.value if approved else RunStatus.INTERRUPTED.value),
                "summary": "" if approved else "Plan approval was denied.",
                "termination_reason": (
                    None if approved else TerminationReason.APPROVAL_DENIED.value
                ),
                "events": runtime._emit(
                    waiting,
                    "approval_decided",
                    {
                        "approval_id": waiting.get("approval_id"),
                        "kind": "plan",
                        "node_id": None,
                        "approved": approved,
                    },
                ),
            }

        def after_awaiting(state: AgentState) -> str:
            return "prepare" if state["status"] == RunStatus.RUNNING.value else "end"

        async def prepare_workspace(state: AgentState) -> AgentState:
            source = Path(state["source_workspace"])
            if (
                not config.isolate_worktree
                or PermissionMode(state["permission"]) is PermissionMode.READ_ONLY
            ):
                return state
            probe = await LocalRunner(source).run(
                "git rev-parse --show-toplevel", permission=PermissionMode.EXECUTE
            )
            if probe.exit_code != 0:
                return {
                    **state,
                    "events": runtime._emit(
                        state,
                        "worktree_skipped",
                        {"reason": "workspace is not a Git repository"},
                    ),
                }
            repository = Path(probe.stdout.strip()).resolve(strict=True)
            target = repository.parent / ".zhixiao-worktrees" / repository.name / state["run_id"]
            try:
                manager = WorktreeManager(repository)
                worktree = await manager.create(state["run_id"], target)
                manifest = await manager.manifest(state["run_id"], worktree)
            except (OSError, RuntimeError, ValueError) as exc:
                return {
                    **state,
                    "status": RunStatus.FAILED.value,
                    "summary": "Task stopped before workspace isolation.",
                    "error": str(exc),
                    "termination_reason": TerminationReason.RUNTIME_ERROR.value,
                    "events": runtime._emit(
                        state,
                        "worktree_failed",
                        {"reason": str(exc)},
                    ),
                }
            artifacts = list(state.get("artifacts", []))
            artifacts.append(
                Artifact(
                    kind="worktree",
                    path=str(worktree),
                    description="isolated task workspace",
                    base_sha=manifest["base_sha"],
                ).model_dump()
            )
            return {
                **state,
                "workspace": str(worktree),
                "artifacts": artifacts,
                "events": runtime._emit(
                    state,
                    "worktree_created",
                    manifest,
                ),
            }

        async def execute(state: AgentState) -> AgentState:
            _interrupt_if_stop_requested(state, config)
            if state.get("status") == RunStatus.INTERRUPTED.value:
                return state
            if state.get("status") == RunStatus.FAILED.value:
                return state
            budget_reason = runtime._budget_reason(state)
            if budget_reason:
                return _budget_failure(runtime, state, budget_reason)
            workspace = Path(state["workspace"])
            context = runtime._tool_context(workspace, state, config)
            messages_in = maybe_compact_messages(list(state["messages"]))
            try:
                turn = await runtime.model.complete(
                    messages_in,
                    tools=runtime.registry.schemas(set(state["allowed_tools"])),
                )
            except Exception as exc:
                return _model_failure(runtime, state, exc)
            usage = runtime._usage(state)
            usage.model_turns += 1
            usage.prompt_tokens += turn.prompt_tokens
            usage.completion_tokens += turn.completion_tokens
            usage.cost_usd += turn.cost_usd
            budget = RunBudget.model_validate(state.get("budgets", {}))
            if usage.tool_calls + len(turn.tool_calls) > budget.max_tool_calls:
                budget_state = cast(AgentState, {**state, "usage": usage.model_dump()})
                return _budget_failure(
                    runtime,
                    budget_state,
                    f"tool call budget exhausted ({budget.max_tool_calls})",
                )
            messages = list(messages_in)
            tool_calls_formatted = []
            for call in turn.tool_calls:
                tool_calls_formatted.append(
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments, ensure_ascii=False),
                        },
                    }
                )
            messages.append(
                {
                    "role": "assistant",
                    "content": turn.content,
                    "tool_calls": tool_calls_formatted,
                }
            )
            events = runtime._emit(
                state,
                "model_turn",
                {
                    "model": turn.model,
                    "tool_calls": [call.name for call in turn.tool_calls],
                    "prompt_tokens": turn.prompt_tokens,
                    "completion_tokens": turn.completion_tokens,
                    "cost_usd": turn.cost_usd,
                    "content": (turn.content or "")[:2_000],
                },
            )
            error: str | None = None
            artifacts = list(state.get("artifacts", []))
            failure_counts = dict(state.get("failure_counts", {}))
            signatures = list(state.get("last_tool_signatures", []))
            current_signatures = [
                json.dumps(
                    {"name": call.name, "arguments": call.arguments},
                    ensure_ascii=False,
                    sort_keys=True,
                )
                for call in turn.tool_calls
            ]
            signatures.extend(current_signatures)
            signatures = signatures[-6:]

            async def _run_one(call: Any) -> tuple[Any, Any]:
                result = await runtime.registry.execute(
                    call.name,
                    call.arguments,
                    context,
                    allowed=set(state["allowed_tools"]),
                )
                return call, result

            if turn.tool_calls and all(call.name in READ_ONLY_TOOLS for call in turn.tool_calls):
                executed = await asyncio.gather(*[_run_one(call) for call in turn.tool_calls])
            else:
                executed = [await _run_one(call) for call in turn.tool_calls]

            for call, result in executed:
                usage.tool_calls += 1
                artifacts.extend(item.model_dump() for item in result.artifacts)
                payload = result.model_dump_json()
                if len(payload) > _MAX_TOOL_RESULT_CHARS:
                    payload = payload[:_MAX_TOOL_RESULT_CHARS] + "...[truncated]"
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": payload,
                    }
                )
                event_state = cast(AgentState, {**state, "events": events})
                events = runtime._emit(
                    event_state,
                    "tool_result",
                    {
                        "call_id": call.id,
                        "tool": call.name,
                        "arguments": call.arguments,
                        "status": result.status.value,
                        "summary": result.summary,
                        "result": result.model_dump(mode="json"),
                    },
                )
                if result.status is ToolStatus.ERROR:
                    error = result.root_cause or result.summary
                    key = error.strip()[:500]
                    failure_counts[key] = failure_counts.get(key, 0) + 1
            summary = turn.content.strip() or state.get("summary", "")
            looped = (
                len(signatures) >= 3
                and len(set(signatures[-3:])) == 1
            ) or any(count >= 3 for count in failure_counts.values())
            mutated = bool(state.get("mutated", False)) or any(
                call.name not in READ_ONLY_TOOLS for call in turn.tool_calls
            )
            if looped:
                error = error or "tool loop detected after three repeated calls or root causes"
            return {
                **state,
                "messages": messages,
                "events": events,
                "iterations": state.get("iterations", 0) + 1,
                "status": RunStatus.RUNNING.value,
                "summary": summary,
                "error": error,
                "_had_tool_calls": bool(turn.tool_calls),
                "artifacts": _deduplicate_artifacts(artifacts),
                "usage": usage.model_dump(),
                "mutated": mutated,
                "failure_counts": failure_counts,
                "last_tool_signatures": signatures,
                "termination_reason": (
                    TerminationReason.TOOL_LOOP.value if looped else state.get("termination_reason")
                ),
            }

        def after_execute(state: AgentState) -> str:
            if _is_interrupted(state):
                return "finalize"
            if state.get("status") == RunStatus.FAILED.value:
                return "verify"
            if state.get("termination_reason") == TerminationReason.TOOL_LOOP.value:
                return "verify"
            if runtime._budget_reason(state):
                return "verify"
            if (
                state.get("_had_tool_calls")
                and state.get("iterations", 0) < config.max_tool_iterations
            ):
                return "execute"
            return "verify"

        async def verify(state: AgentState) -> AgentState:
            _interrupt_if_stop_requested(state, config)
            if state.get("status") == RunStatus.INTERRUPTED.value:
                return state
            permission = PermissionMode(state["permission"])
            commands = list(config.verification_commands)
            command = config.test_command or _detect_test_command(Path(state["workspace"]))
            if not commands and command:
                commands.append(command)
            if state["task_type"] in {TaskType.EXPLORE.value, TaskType.REVIEW.value}:
                commands = []
            if not commands or permission not in {PermissionMode.EXECUTE, PermissionMode.FULL}:
                reason = "no runnable test command or execute permission"
                outcome = (
                    VerificationOutcome.BLOCKED
                    if state.get("mutated", False) and not config.allow_unverified
                    else VerificationOutcome.SKIPPED
                )
                verification = VerificationResult(
                    outcome=outcome,
                    reason=reason,
                    waived=bool(config.allow_unverified),
                    waiver_reason=config.allow_unverified,
                )
                return {
                    **state,
                    "status": RunStatus.VERIFYING.value,
                    "test_command": commands[0] if commands else command,
                    "test_exit_code": None,
                    "verification": verification.model_dump(mode="json"),
                    "events": runtime._emit(
                        state,
                        "verification_skipped",
                        {
                            "reason": reason,
                            "outcome": outcome.value,
                            "waived": verification.waived,
                        },
                    ),
                }
            context = runtime._tool_context(Path(state["workspace"]), state, config)
            messages = list(state["messages"])
            stages: list[VerificationStage] = []
            artifacts = list(state.get("artifacts", []))
            exit_code: int | None = 0
            failure: str | None = None
            for index, verification_command in enumerate(commands):
                result = await runtime.registry.execute(
                    "run_tests",
                    {"command": verification_command, "timeout": config.command_timeout},
                    context,
                    allowed=set(state["allowed_tools"]),
                )
                stage_exit_code = (
                    (result.data or {}).get("exit_code")
                    if isinstance(result.data, dict)
                    else None
                )
                stage_outcome = (
                    VerificationOutcome.PASSED
                    if result.status is ToolStatus.SUCCESS and stage_exit_code == 0
                    else VerificationOutcome.FAILED
                )
                stage = VerificationStage(
                    name=("focused" if index == 0 else f"stage_{index + 1}"),
                    command=verification_command,
                    outcome=stage_outcome,
                    exit_code=stage_exit_code,
                    summary=result.summary,
                    artifacts=result.artifacts,
                )
                stages.append(stage)
                artifacts.extend(item.model_dump() for item in result.artifacts)
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Verification result for `{verification_command}`:\n"
                            f"{result.model_dump_json()}"
                        ),
                    }
                )
                event_state = cast(AgentState, {**state, "events": state.get("events", [])})
                state = cast(
                    AgentState,
                    {
                        **state,
                        "events": runtime._emit(
                            event_state,
                            "verification_finished",
                            {
                                "stage": stage.name,
                                "command": verification_command,
                                "exit_code": stage_exit_code,
                                "status": result.status.value,
                            },
                        ),
                    },
                )
                if stage_outcome is VerificationOutcome.FAILED:
                    exit_code = stage_exit_code if stage_exit_code is not None else 1
                    failure = result.root_cause or result.summary
                    break
            verification = VerificationResult(
                outcome=(
                    VerificationOutcome.PASSED
                    if all(stage.outcome is VerificationOutcome.PASSED for stage in stages)
                    else VerificationOutcome.FAILED
                ),
                reason=(
                    "all required verification stages passed"
                    if exit_code == 0
                    else failure or "verification failed"
                ),
                stages=stages,
            )
            return {
                **state,
                "messages": messages,
                "status": RunStatus.VERIFYING.value,
                "test_command": commands[0],
                "test_exit_code": exit_code,
                "error": failure,
                "verification": verification.model_dump(mode="json"),
                "artifacts": _deduplicate_artifacts(artifacts),
                "events": state["events"],
            }

        def after_verify(state: AgentState) -> str:
            if _is_interrupted(state):
                return "finalize"
            if state.get("test_exit_code") not in (None, 0):
                if state.get("repair_rounds", 0) < config.max_repair_rounds:
                    return "repair"
            return "finalize"

        async def repair(state: AgentState) -> AgentState:
            return {
                **state,
                "repair_rounds": state.get("repair_rounds", 0) + 1,
                "iterations": 0,
                "events": runtime._emit(
                    state,
                    "repair_started",
                    {"round": state.get("repair_rounds", 0) + 1, "error": state.get("error")},
                ),
            }

        async def finalize(state: AgentState) -> AgentState:
            context = runtime._tool_context(Path(state["workspace"]), state, config)
            diff = ""
            if state.get("mutated", False):
                diff_result = await runtime.registry.execute("git_diff", {}, context)
                diff = diff_result.data if diff_result.status is ToolStatus.SUCCESS else ""
            verification = VerificationResult.model_validate(state.get("verification", {}))
            budget_reason = runtime._budget_reason(state)
            termination = state.get("termination_reason")
            if budget_reason and termination is None:
                termination = TerminationReason.BUDGET_EXHAUSTED.value
            interrupted = _is_interrupted(state) or (
                termination == TerminationReason.INTERRUPTED.value
            )
            failed = (not interrupted) and (
                state.get("test_exit_code") not in (None, 0)
                or verification.outcome in {
                    VerificationOutcome.FAILED,
                    VerificationOutcome.BLOCKED,
                }
                or termination in {
                    TerminationReason.BUDGET_EXHAUSTED.value,
                    TerminationReason.MODEL_ERROR.value,
                    TerminationReason.TOOL_LOOP.value,
                    TerminationReason.RUNTIME_ERROR.value,
                }
            )
            if interrupted:
                status = RunStatus.INTERRUPTED
                termination = TerminationReason.INTERRUPTED.value
            else:
                status = RunStatus.FAILED if failed else RunStatus.SUCCEEDED
            artifacts = list(state.get("artifacts", []))
            if diff:
                patch_artifact = _write_patch_artifact(state, diff)
                artifacts.append(patch_artifact.model_dump())
            if termination is None:
                termination = (
                    TerminationReason.VERIFICATION_FAILED.value
                    if verification.outcome is VerificationOutcome.FAILED
                    else TerminationReason.VERIFICATION_BLOCKED.value
                    if verification.outcome is VerificationOutcome.BLOCKED
                    else TerminationReason.COMPLETED.value
                )
            summary = state.get("summary") or (
                "run interrupted"
                if interrupted
                else "Task completed and verified."
                if not failed
                else "Task stopped because verification failed."
            )
            result: AgentState = {
                **state,
                "status": status.value,
                "diff": diff or "",
                "artifacts": artifacts,
                "summary": summary,
                "verification": verification.model_dump(mode="json"),
                "termination_reason": termination,
                "usage": runtime._usage(state, elapsed=True).model_dump(),
                "next_actions": _next_actions(
                    status, verification, termination, run_id=state["run_id"]
                ),
                "events": runtime._emit(
                    state,
                    "run_finished",
                    {
                        "status": status.value,
                        "test_exit_code": state.get("test_exit_code"),
                        "termination_reason": termination,
                        "verification": verification.outcome.value,
                    },
                ),
            }
            return result

        if config.workflow_definition is not None:
            workflow = WorkflowDefinition.model_validate(config.workflow_definition)
            role_handlers = {
                "planner": plan,
                "explorer": discover,
                "tester": verify,
            }

            def pending_workflow_approval(state: AgentState) -> WorkflowNode | None:
                approved_nodes = set(state.get("approved_nodes", []))
                for workflow_node in workflow.nodes:
                    if workflow_node.approval_required and workflow_node.id not in approved_nodes:
                        return workflow_node
                return None

            async def workflow_approval_gate(state: AgentState) -> AgentState:
                current: AgentState = {**state}
                node = pending_workflow_approval(current)
                if node is None:
                    return current
                approval_id = runtime._approval_id(current, "workflow", node.id)
                decision = interrupt(
                    {
                        "approval_id": approval_id,
                        "kind": "workflow_node",
                        "run_id": current["run_id"],
                        "node_id": node.id,
                        "role": node.role,
                    }
                )
                approved = bool(
                    decision.get("approved", False) if isinstance(decision, dict) else decision
                )
                if not approved:
                    return {
                        **current,
                        "status": RunStatus.INTERRUPTED.value,
                        "summary": f"Approval denied for workflow node {node.id}.",
                        "termination_reason": TerminationReason.APPROVAL_DENIED.value,
                        "events": runtime._emit(
                            current,
                            "approval_decided",
                            {
                                "approval_id": approval_id,
                                "kind": "workflow_node",
                                "node_id": node.id,
                                "approved": False,
                            },
                        ),
                    }
                approved_nodes = set(current.get("approved_nodes", []))
                approved_nodes.add(node.id)
                updated: AgentState = {
                    **current,
                    "approved_nodes": sorted(approved_nodes),
                    "status": RunStatus.RUNNING.value,
                    "termination_reason": None,
                }
                return {
                    **updated,
                    "events": runtime._emit(
                        updated,
                        "approval_decided",
                        {
                            "approval_id": approval_id,
                            "kind": "workflow_node",
                            "node_id": node.id,
                            "approved": True,
                        },
                    ),
                }

            def after_workflow_approval_gate(state: AgentState) -> str:
                if state.get("status") == RunStatus.INTERRUPTED.value:
                    return "end"
                return "approve" if pending_workflow_approval(state) is not None else "prepare"

            def configured_node(node: WorkflowNode) -> Any:
                async def invoke(state: AgentState) -> AgentState:
                    current: AgentState = {
                        **state,
                        "workflow_node": node.id,
                        "events": runtime._emit(
                            state,
                            "workflow_node_started",
                            {"node_id": node.id, "role": node.role},
                        ),
                    }
                    if node.tool_allowlist:
                        route_tools = set(
                            current.get("route_allowed_tools", current.get("allowed_tools", []))
                        )
                        current["allowed_tools"] = sorted(route_tools & set(node.tool_allowlist))
                    else:
                        current["allowed_tools"] = list(
                            current.get("route_allowed_tools", current.get("allowed_tools", []))
                        )

                    approved_nodes = set(current.get("approved_nodes", []))
                    if node.approval_required and node.id not in approved_nodes:
                        approval_id = runtime._approval_id(current, "workflow", node.id)
                        return {
                            **current,
                            "status": RunStatus.AWAITING_APPROVAL.value,
                            "termination_reason": TerminationReason.AWAITING_APPROVAL.value,
                            "approval_id": approval_id,
                            "events": runtime._emit(
                                current,
                                "approval_required",
                                {
                                    "approval_id": approval_id,
                                    "kind": "workflow_node",
                                    "node_id": node.id,
                                    "role": node.role,
                                },
                            ),
                        }

                    handler = role_handlers.get(node.role, execute)
                    last_error: Exception | None = None
                    for attempt in range(node.retry_limit + 1):
                        try:
                            updated = await handler(current)
                            if node.role in {"implementer", "reviewer", "knowledge"}:
                                while (
                                    updated.get("_had_tool_calls", False)
                                    and updated.get("iterations", 0) < config.max_tool_iterations
                                ):
                                    updated = await execute(updated)
                        except Exception as exc:
                            last_error = exc
                            updated = {
                                **current,
                                "error": str(exc),
                                "status": RunStatus.RUNNING.value,
                            }
                        failed = (
                            bool(updated.get("error"))
                            if node.role != "tester"
                            else updated.get("test_exit_code") not in (None, 0)
                        )
                        if not failed or attempt >= node.retry_limit:
                            current = updated
                            break
                        current = {
                            **updated,
                            "events": runtime._emit(
                                updated,
                                "workflow_node_retry",
                                {
                                    "node_id": node.id,
                                    "attempt": attempt + 2,
                                    "reason": updated.get("error") or "verification failed",
                                },
                            ),
                        }
                    if last_error is not None and not current.get("error"):
                        current["error"] = str(last_error)
                    return {
                        **current,
                        "events": runtime._emit(
                            current,
                            "workflow_node_finished",
                            {
                                "node_id": node.id,
                                "role": node.role,
                                "failed": (
                                    current.get("test_exit_code") not in (None, 0)
                                    if node.role == "tester"
                                    else bool(current.get("error"))
                                ),
                            },
                        ),
                    }

                return invoke

            builder = StateGraph(AgentState)
            builder.add_node("intake", intake)
            builder.add_node("workflow_approval_gate", workflow_approval_gate)
            builder.add_node("prepare_workspace", prepare_workspace)
            builder.add_node("finalize", finalize)
            node_names = {node.id: f"workflow_{node.id}" for node in workflow.nodes}
            node_by_id = {node.id: node for node in workflow.nodes}
            for node in workflow.nodes:
                builder.add_node(node_names[node.id], configured_node(node))
            builder.add_edge(START, "intake")
            builder.add_edge("intake", "workflow_approval_gate")
            builder.add_conditional_edges(
                "workflow_approval_gate",
                after_workflow_approval_gate,
                {
                    "approve": "workflow_approval_gate",
                    "prepare": "prepare_workspace",
                    "end": END,
                },
            )
            builder.add_edge("prepare_workspace", node_names[cast(str, workflow.entrypoint)])

            for node_id, node_name in node_names.items():
                node = node_by_id[node_id]

                def route(state: AgentState, *, current_node: WorkflowNode = node) -> str:
                    if state.get("status") in {
                        RunStatus.INTERRUPTED.value,
                        RunStatus.AWAITING_APPROVAL.value,
                    }:
                        return "__end__"
                    failed = (
                        state.get("test_exit_code") not in (None, 0)
                        if current_node.role == "tester"
                        else bool(state.get("error"))
                    )
                    return workflow.next_node(current_node.id, failed=failed) or "__finalize__"

                path_map: dict[Hashable, str] = {
                    edge.target: node_names[edge.target] for edge in workflow.outgoing(node_id)
                }
                path_map["__finalize__"] = "finalize"
                path_map["__end__"] = END
                builder.add_conditional_edges(node_name, route, path_map)
            builder.add_edge("finalize", END)
            return builder.compile(checkpointer=checkpointer)

        builder = StateGraph(AgentState)
        builder.add_node("intake", intake)
        builder.add_node("discover", discover)
        builder.add_node("plan", plan)
        builder.add_node("awaiting", awaiting)
        builder.add_node("prepare_workspace", prepare_workspace)
        builder.add_node("execute", execute)
        builder.add_node("verify", verify)
        builder.add_node("repair", repair)
        builder.add_node("finalize", finalize)
        builder.add_edge(START, "intake")
        builder.add_edge("intake", "discover")
        builder.add_edge("discover", "plan")
        builder.add_conditional_edges(
            "plan",
            after_plan,
            {"awaiting": "awaiting", "execute": "prepare_workspace", "end": END},
        )
        builder.add_conditional_edges(
            "awaiting", after_awaiting, {"prepare": "prepare_workspace", "end": END}
        )
        builder.add_edge("prepare_workspace", "execute")
        builder.add_conditional_edges(
            "execute",
            after_execute,
            {"execute": "execute", "verify": "verify", "finalize": "finalize"},
        )
        builder.add_conditional_edges(
            "verify", after_verify, {"repair": "repair", "finalize": "finalize"}
        )
        builder.add_edge("repair", "execute")
        builder.add_edge("finalize", END)
        return builder.compile(checkpointer=checkpointer)

    @asynccontextmanager
    async def _checkpointer(self) -> AsyncIterator[Any]:
        if self.checkpointer is not None:
            yield self.checkpointer
            return
        async with AsyncSqliteSaver.from_conn_string(str(self.checkpoint_path)) as saver:
            yield saver

    async def run(
        self,
        prompt: str,
        workspace: Path,
        config: RuntimeConfig | None = None,
        *,
        run_id: str | None = None,
    ) -> RunResult:
        runtime_config = config or RuntimeConfig()
        resolved_workspace = workspace.resolve(strict=True)
        identifier = run_id or uuid.uuid4().hex
        initial: AgentState = {
            "run_id": identifier,
            "prompt": prompt,
            "workspace": str(resolved_workspace),
            "source_workspace": str(resolved_workspace),
            "route_allowed_tools": [],
            "workflow_node": "",
            "permission": runtime_config.permission.value,
            "events": [],
            "artifacts": [],
            "messages": [],
            "plan": [],
            "iterations": 0,
            "repair_rounds": 0,
            "status": RunStatus.PENDING.value,
            "summary": "",
            "diff": "",
            "error": None,
            "test_command": runtime_config.test_command,
            "test_exit_code": None,
            "approved": runtime_config.approved,
            "ops_approved": runtime_config.ops_approved,
            "ops_capabilities": sorted(runtime_config.ops_capabilities),
            "network_approved": runtime_config.network_approved,
            "network_capabilities": sorted(runtime_config.network_capabilities),
            "require_plan_approval": runtime_config.require_plan_approval,
            "mode": str(
                (runtime_config.tool_metadata or {}).get("mode") or runtime_config.mode or "ask"
            ),
            "approved_nodes": [],
            "approval_id": "",
            "verification": VerificationResult().model_dump(mode="json"),
            "termination_reason": None,
            "usage": RunUsage().model_dump(),
            "budgets": runtime_config.budget.model_dump(),
            "next_actions": [],
            "started_at": time.monotonic(),
            "mutated": False,
            "failure_counts": {},
            "last_tool_signatures": [],
        }
        async with self._checkpointer() as checkpointer:
            graph = self._build_graph(runtime_config, checkpointer)
            final: AgentState = {**initial}
            # Track by sequence, not list length: _emit truncates events in state.
            seen_sequence = 0
            async for update in graph.astream(
                initial,
                config={"configurable": {"thread_id": identifier}},
                stream_mode="values",
            ):
                final = cast(AgentState, update)
                events = final.get("events", [])
                if runtime_config.on_event:
                    for event in events:
                        sequence = int(event.get("sequence") or 0)
                        if sequence > seen_sequence:
                            await runtime_config.on_event(event)
                            seen_sequence = sequence
            final = await self._pending_interrupt_state(graph, identifier, final)
            if runtime_config.on_event:
                for event in final.get("events", []):
                    sequence = int(event.get("sequence") or 0)
                    if sequence > seen_sequence:
                        await runtime_config.on_event(event)
                        seen_sequence = sequence
        return _to_result(final, runtime_config)

    async def resume(self, run_id: str, *, approved: bool, config: RuntimeConfig) -> RunResult:
        async with self._checkpointer() as checkpointer:
            graph = self._build_graph(config, checkpointer)
            final = cast(
                AgentState,
                await graph.ainvoke(
                    Command(resume={"approved": approved}),
                    config={"configurable": {"thread_id": run_id}},
                ),
            )
            final = await self._pending_interrupt_state(graph, run_id, final)
        return _to_result(final, config)

    async def _pending_interrupt_state(
        self,
        graph: Any,
        run_id: str,
        state: AgentState,
    ) -> AgentState:
        snapshot = await graph.aget_state({"configurable": {"thread_id": run_id}})
        interrupts = getattr(snapshot, "interrupts", ())
        if not interrupts:
            return state
        value = getattr(interrupts[0], "value", {})
        data = dict(value) if isinstance(value, dict) else {"value": value}
        kind = str(data.get("kind") or "")
        if kind == "operator_stop":
            return {
                **state,
                "status": RunStatus.INTERRUPTED.value,
                "termination_reason": TerminationReason.INTERRUPTED.value,
                "summary": "run interrupted",
                "events": self._emit(state, "run_interrupted", {"run_id": run_id, **data}),
                "next_actions": (
                    [f"zhixiao resume {run_id}"] if run_id else ["resume the interrupted run"]
                ),
            }
        data.setdefault("approval_id", self._approval_id(state, kind or "task"))
        return {
            **state,
            "status": RunStatus.AWAITING_APPROVAL.value,
            "termination_reason": TerminationReason.AWAITING_APPROVAL.value,
            "approval_id": str(data["approval_id"]),
            "events": self._emit(state, "approval_required", data),
            "next_actions": [f"approve or deny {data['approval_id']}"],
        }


def _control_path(state_dir: Path, run_id: str) -> Path:
    """Return {state_dir}/control/{run_id} cooperative-stop file.

    Duplicated from session_controller.control_path to avoid a circular import.
    """
    return Path(state_dir).expanduser().resolve() / "control" / run_id


def _runtime_state_dir(config: RuntimeConfig) -> Path:
    if config.state_dir is not None:
        return Path(config.state_dir)
    return Path(os.environ.get("ZHIXIAO_STATE_DIR", Path.home() / ".zhixiao"))


def _is_interrupted(state: AgentState) -> bool:
    return (
        state.get("status") == RunStatus.INTERRUPTED.value
        or state.get("termination_reason") == TerminationReason.INTERRUPTED.value
    )


def _interrupt_if_stop_requested(state: AgentState, config: RuntimeConfig) -> None:
    """Pause on a cooperative stop file via LangGraph interrupt().

    Returning INTERRUPTED and routing to finalize/END cannot be resumed with
    ``Command(resume=...)``. Unlink the stop file first so resume does not
    immediately re-stop, then interrupt the graph in-place.
    """
    run_id = str(state.get("run_id") or "")
    if not run_id:
        return
    stop_file = _control_path(_runtime_state_dir(config), run_id)
    if not stop_file.is_file():
        return
    # Consume the stop file so resume_local is not immediately re-interrupted.
    try:
        stop_file.unlink()
    except OSError:
        pass
    interrupt({"kind": "operator_stop", "run_id": run_id})


def _resolve_work_mode(config: RuntimeConfig, state: AgentState) -> str:
    """Resolve CLI/TUI work mode from metadata, seeded state, or RuntimeConfig.

    CLI currently stores WorkMode in tool_metadata. Prefer that over the
    RuntimeConfig default so ``--mode`` is honored before consumers pass
    ``mode=`` into RuntimeConfig.
    """
    metadata_mode = (config.tool_metadata or {}).get("mode")
    raw = metadata_mode or state.get("mode") or config.mode or "ask"
    if not isinstance(raw, str):
        return "ask"
    normalized = raw.strip().lower()
    return normalized or "ask"


def _detect_test_command(workspace: Path) -> str | None:
    if (workspace / "pyproject.toml").is_file() or (workspace / "pytest.ini").is_file():
        return "python -m pytest -q"
    if (workspace / "package.json").is_file():
        return "npm test -- --run"
    if (workspace / "go.mod").is_file():
        return "go test ./..."
    if (workspace / "Cargo.toml").is_file():
        return "cargo test"
    return None


def _to_result(state: AgentState, config: RuntimeConfig | None = None) -> RunResult:
    return RunResult(
        run_id=state["run_id"],
        status=RunStatus(state["status"]),
        summary=state.get("summary", ""),
        task_type=TaskType(state.get("task_type", TaskType.EXPLORE.value)),
        plan=state.get("plan", []),
        artifacts=[Artifact.model_validate(item) for item in state.get("artifacts", [])],
        test_command=state.get("test_command"),
        test_exit_code=state.get("test_exit_code"),
        diff=state.get("diff", ""),
        events=[AgentEvent.model_validate(item) for item in state.get("events", [])],
        error=state.get("error"),
        verification=VerificationResult.model_validate(state.get("verification", {})),
        termination_reason=_termination_reason(state.get("termination_reason")),
        usage=RunUsage.model_validate(state.get("usage", {})),
        budgets=RunBudget.model_validate(
            state.get("budgets", (config or RuntimeConfig()).budget.model_dump())
        ),
        next_actions=state.get("next_actions", []),
    )


def _model_failure(runtime: AgentRuntime, state: AgentState, exc: Exception) -> AgentState:
    return {
        **state,
        "status": RunStatus.FAILED.value,
        "summary": "Task stopped because the model request failed.",
        "error": str(exc),
        "termination_reason": TerminationReason.MODEL_ERROR.value,
        "events": runtime._emit(
            state,
            "model_error",
            {"error_type": type(exc).__name__, "message": str(exc)},
        ),
    }


def _termination_reason(value: str | None) -> TerminationReason | None:
    return TerminationReason(value) if value else None


def _budget_failure(runtime: AgentRuntime, state: AgentState, reason: str) -> AgentState:
    return {
        **state,
        "status": RunStatus.FAILED.value,
        "summary": f"Task stopped because {reason}.",
        "error": reason,
        "termination_reason": TerminationReason.BUDGET_EXHAUSTED.value,
        "usage": runtime._usage(state, elapsed=True).model_dump(),
        "events": runtime._emit(state, "budget_exhausted", {"reason": reason}),
    }


def _deduplicate_artifacts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        key = (str(item.get("kind", "")), str(item.get("path", "")))
        unique[key] = item
    return list(unique.values())


def _write_patch_artifact(state: AgentState, diff: str) -> Artifact:
    workspace = Path(state["workspace"])
    artifact_dir = workspace / ".zhixiao" / "artifacts" / state["run_id"]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    patch_path = artifact_dir / "changes.patch"
    encoded = diff.encode("utf-8")
    patch_path.write_bytes(encoded)
    base_sha: str | None = None
    source = Path(state.get("source_workspace", state["workspace"]))
    head_file = source / ".git" / "HEAD"
    if head_file.is_file():
        reference = head_file.read_text(encoding="utf-8", errors="replace").strip()
        if reference.startswith("ref: "):
            ref_file = source / ".git" / reference.removeprefix("ref: ")
            if ref_file.is_file():
                base_sha = ref_file.read_text(encoding="utf-8", errors="replace").strip()
        else:
            base_sha = reference
    return Artifact(
        kind="git_diff",
        path=str(patch_path),
        description="applicable binary-safe working tree patch",
        sha256=hashlib.sha256(encoded).hexdigest(),
        size_bytes=len(encoded),
        mime_type=mimetypes.guess_type(patch_path.name)[0] or "text/x-diff",
        base_sha=base_sha,
    )


def _next_actions(
    status: RunStatus,
    verification: VerificationResult,
    termination: str,
    *,
    run_id: str = "",
) -> list[str]:
    if status is RunStatus.INTERRUPTED or termination == TerminationReason.INTERRUPTED.value:
        return [f"zhixiao resume {run_id}"] if run_id else ["resume the interrupted run"]
    if status is RunStatus.SUCCEEDED:
        return []
    if verification.outcome is VerificationOutcome.BLOCKED:
        return ["grant execute permission or supply an explicit unverified waiver"]
    if verification.outcome is VerificationOutcome.FAILED:
        return ["inspect the failed verification stage and repair the root cause"]
    if termination == TerminationReason.BUDGET_EXHAUSTED.value:
        return ["increase the relevant run budget after reviewing usage"]
    if termination == TerminationReason.MODEL_ERROR.value:
        return ["check model credentials, availability, and fallback configuration"]
    return ["inspect the final error and event timeline"]
