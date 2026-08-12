from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Hashable
from contextlib import asynccontextmanager
from dataclasses import dataclass
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
    RunResult,
    RunStatus,
    TaskType,
    ToolStatus,
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
    _had_tool_calls: bool
    source_workspace: str
    route_allowed_tools: list[str]
    workflow_node: str


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
            sorted_allowed = sorted(allowed)
            return {
                **state,
                "task_type": task_type.value,
                "allowed_tools": sorted_allowed,
                "route_allowed_tools": sorted_allowed,
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
            }
            if (
                state["require_plan_approval"]
                and PermissionMode(state["permission"]) is not PermissionMode.READ_ONLY
                and not state["approved"]
            ):
                updated["status"] = RunStatus.AWAITING_APPROVAL.value
                updated["events"] = runtime._emit(updated, "approval_required", {"kind": "plan"})
            return updated

        def after_plan(state: AgentState) -> str:
            return "awaiting" if state["status"] == RunStatus.AWAITING_APPROVAL.value else "execute"

        async def awaiting(state: AgentState) -> AgentState:
            waiting: AgentState = {**state}
            decision = interrupt(
                {"kind": "plan", "run_id": state["run_id"], "plan": state.get("plan", [])}
            )
            approved = bool(
                decision.get("approved", False) if isinstance(decision, dict) else decision
            )
            return {
                **waiting,
                "approved": approved,
                "status": (RunStatus.RUNNING.value if approved else RunStatus.INTERRUPTED.value),
                "summary": "" if approved else "Plan approval was denied.",
                "events": runtime._emit(
                    waiting,
                    "approval_decided",
                    {"kind": "plan", "approved": approved},
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
            worktree = await WorktreeManager(repository).create(state["run_id"], target)
            artifacts = list(state.get("artifacts", []))
            artifacts.append(
                Artifact(
                    kind="worktree",
                    path=str(worktree),
                    description="isolated task workspace",
                ).model_dump()
            )
            return {
                **state,
                "workspace": str(worktree),
                "artifacts": artifacts,
                "events": runtime._emit(
                    state,
                    "worktree_created",
                    {"path": str(worktree), "branch": WorktreeManager.branch_name(state["run_id"])},
                ),
            }

        async def execute(state: AgentState) -> AgentState:
            workspace = Path(state["workspace"])
            context = runtime._tool_context(workspace, state, config)
            messages_in = maybe_compact_messages(list(state["messages"]))
            turn = await runtime.model.complete(
                messages_in,
                tools=runtime.registry.schemas(set(state["allowed_tools"])),
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
            summary = turn.content.strip() or state.get("summary", "")
            return {
                **state,
                "messages": messages,
                "events": events,
                "iterations": state.get("iterations", 0) + 1,
                "status": RunStatus.RUNNING.value,
                "summary": summary,
                "error": error,
                "_had_tool_calls": bool(turn.tool_calls),
            }

        def after_execute(state: AgentState) -> str:
            if (
                state.get("_had_tool_calls")
                and state.get("iterations", 0) < config.max_tool_iterations
            ):
                return "execute"
            return "verify"

        async def verify(state: AgentState) -> AgentState:
            permission = PermissionMode(state["permission"])
            command = config.test_command or _detect_test_command(Path(state["workspace"]))
            if state["task_type"] in {TaskType.EXPLORE.value, TaskType.REVIEW.value}:
                command = None
            if command is None or permission not in {PermissionMode.EXECUTE, PermissionMode.FULL}:
                return {
                    **state,
                    "status": RunStatus.VERIFYING.value,
                    "test_command": command,
                    "test_exit_code": None,
                    "events": runtime._emit(
                        state,
                        "verification_skipped",
                        {"reason": "no runnable test command or execute permission"},
                    ),
                }
            context = runtime._tool_context(Path(state["workspace"]), state, config)
            result = await runtime.registry.execute(
                "run_tests",
                {"command": command, "timeout": config.command_timeout},
                context,
                allowed=set(state["allowed_tools"]),
            )
            exit_code = (
                (result.data or {}).get("exit_code") if isinstance(result.data, dict) else None
            )
            messages = list(state["messages"])
            messages.append(
                {
                    "role": "user",
                    "content": f"Verification result for `{command}`:\n{result.model_dump_json()}",
                }
            )
            return {
                **state,
                "messages": messages,
                "status": RunStatus.VERIFYING.value,
                "test_command": command,
                "test_exit_code": exit_code,
                "error": result.root_cause if result.status is ToolStatus.ERROR else None,
                "events": runtime._emit(
                    state,
                    "verification_finished",
                    {"command": command, "exit_code": exit_code, "status": result.status.value},
                ),
            }

        def after_verify(state: AgentState) -> str:
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
            diff_result = await runtime.registry.execute("git_diff", {}, context)
            diff = diff_result.data if diff_result.status is ToolStatus.SUCCESS else ""
            failed = state.get("test_exit_code") not in (None, 0)
            status = RunStatus.FAILED if failed else RunStatus.SUCCEEDED
            artifacts = list(state.get("artifacts", []))
            if diff:
                artifacts.append(
                    Artifact(
                        kind="git_diff",
                        path=state["workspace"],
                        description="working tree patch",
                    ).model_dump()
                )
            summary = state.get("summary") or (
                "Task completed and verified."
                if not failed
                else "Task stopped because verification failed."
            )
            result: AgentState = {
                **state,
                "status": status.value,
                "diff": diff or "",
                "artifacts": artifacts,
                "summary": summary,
                "events": runtime._emit(
                    state,
                    "run_finished",
                    {"status": status.value, "test_exit_code": state.get("test_exit_code")},
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

                    if node.approval_required and not current.get("approved", False):
                        decision = interrupt(
                            {
                                "kind": "workflow_node",
                                "run_id": current["run_id"],
                                "node_id": node.id,
                                "role": node.role,
                            }
                        )
                        approved = bool(
                            decision.get("approved", False)
                            if isinstance(decision, dict)
                            else decision
                        )
                        if not approved:
                            return {
                                **current,
                                "status": RunStatus.INTERRUPTED.value,
                                "summary": f"Approval denied for workflow node {node.id}.",
                                "events": runtime._emit(
                                    current,
                                    "approval_decided",
                                    {
                                        "kind": "workflow_node",
                                        "node_id": node.id,
                                        "approved": False,
                                    },
                                ),
                            }
                        current["approved"] = True

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
            builder.add_node("prepare_workspace", prepare_workspace)
            builder.add_node("finalize", finalize)
            node_names = {node.id: f"workflow_{node.id}" for node in workflow.nodes}
            node_by_id = {node.id: node for node in workflow.nodes}
            for node in workflow.nodes:
                builder.add_node(node_names[node.id], configured_node(node))
            builder.add_edge(START, "intake")
            builder.add_edge("intake", "prepare_workspace")
            builder.add_edge("prepare_workspace", node_names[cast(str, workflow.entrypoint)])

            for node_id, node_name in node_names.items():
                node = node_by_id[node_id]

                def route(state: AgentState, *, current_node: WorkflowNode = node) -> str:
                    if state.get("status") == RunStatus.INTERRUPTED.value:
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
            "plan", after_plan, {"awaiting": "awaiting", "execute": "prepare_workspace"}
        )
        builder.add_conditional_edges(
            "awaiting", after_awaiting, {"prepare": "prepare_workspace", "end": END}
        )
        builder.add_edge("prepare_workspace", "execute")
        builder.add_conditional_edges(
            "execute", after_execute, {"execute": "execute", "verify": "verify"}
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
        return _to_result(final)

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
        return _to_result(final)


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


def _to_result(state: AgentState) -> RunResult:
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
    )
