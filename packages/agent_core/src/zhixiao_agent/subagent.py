from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .model import CodingModel
from .runner import LocalRunner
from .tools import ToolContext, ToolRegistry, build_default_registry
from .types import PermissionMode, ToolStatus

EventSink = Callable[[dict[str, Any]], Awaitable[None]]
WorkspaceFactory = Callable[[], Path]
SubAgentHandler = Callable[[str], Awaitable[dict[str, Any]] | dict[str, Any]]

DEFAULT_SUB_AGENT_ALLOWLIST = frozenset(
    {
        "list_directory",
        "read_file",
        "grep",
        "git_status",
        "knowledge_search",
    }
)

_SUB_AGENT_SYSTEM = """You are a Zhixiao sub-agent with a read-only tool budget.
Complete the delegated task using only the provided tools.
Stay inside the workspace. Prefer concise factual answers.
When finished, reply with a short summary and no further tool calls.
"""


async def run_sub_agent(
    task: str,
    *,
    model: CodingModel,
    workspace: Path,
    permission: PermissionMode,
    ops_approved: bool,
    network_approved: bool,
    tool_allowlist: frozenset[str] | set[str] | None = None,
    max_iterations: int = 5,
    parent_run_id: str | None = None,
    on_event: EventSink | None = None,
    registry: ToolRegistry | None = None,
    approved: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run an isolated sub-agent with a bounded tool allowlist and depth limit."""
    run_id = uuid.uuid4().hex
    sequence = 0

    async def emit(event: str, data: dict[str, Any]) -> None:
        nonlocal sequence
        sequence += 1
        await _emit(
            on_event,
            event=event,
            data=data,
            parent_run_id=parent_run_id,
            run_id=run_id,
            sequence=sequence,
        )

    parent_depth = int((metadata or {}).get("sub_agent_depth", 0))
    child_depth = parent_depth + 1
    if child_depth > 1:
        blocked_payload = {
            "status": "blocked",
            "summary": "sub-agent nesting beyond depth 1 is refused",
            "task": task,
            "parent_run": parent_run_id,
            "sub_agent_depth": child_depth,
            "error": "sub_agent_depth exceeds limit",
        }
        await emit("sub_agent_blocked", blocked_payload)
        return blocked_payload

    requested = (
        DEFAULT_SUB_AGENT_ALLOWLIST
        if tool_allowlist is None
        else frozenset(tool_allowlist)
    )
    allowlist = frozenset(requested & DEFAULT_SUB_AGENT_ALLOWLIST)
    # Nested delegation is never available inside a sub-agent window.
    allowlist = frozenset(name for name in allowlist if name != "sub_agent")
    tools = registry or build_default_registry()
    allowlist = frozenset(allowlist & tools.names())
    resolved = workspace.resolve(strict=True)
    child_metadata = {
        **dict(metadata or {}),
        "sub_agent_depth": child_depth,
        # Prevent accidental nested handlers unless an outer adapter re-injects one.
        "sub_agent": None,
    }
    context = ToolContext(
        workspace=resolved,
        permission=PermissionMode.READ_ONLY,
        runner=LocalRunner(resolved),
        approved=False,
        ops_approved=False,
        network_approved=False,
        metadata=child_metadata,
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SUB_AGENT_SYSTEM},
        {"role": "user", "content": f"Delegated task:\n{task}"},
    ]
    await emit(
        "sub_agent_started",
        {"task": task, "run_id": run_id, "sub_agent_depth": child_depth},
    )

    summary = ""
    error: str | None = None
    tool_trace: list[dict[str, Any]] = []
    for iteration in range(max(1, max_iterations)):
        turn = await model.complete(messages, tools=tools.schemas(set(allowlist)))
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
        await emit(
            "sub_agent_model_turn",
            {
                "run_id": run_id,
                "iteration": iteration + 1,
                "tool_calls": [call.name for call in turn.tool_calls],
                "content": (turn.content or "")[:2_000],
            },
        )
        if not turn.tool_calls:
            summary = (turn.content or "").strip() or summary
            break

        for call in turn.tool_calls:
            result = await tools.execute(
                call.name,
                call.arguments,
                context,
                allowed=set(allowlist),
            )
            tool_payload = result.model_dump_json()
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.name,
                    "content": tool_payload,
                }
            )
            tool_trace.append(
                {
                    "tool": call.name,
                    "status": result.status.value,
                    "summary": result.summary,
                }
            )
            await emit(
                "sub_agent_tool_result",
                {
                    "run_id": run_id,
                    "tool": call.name,
                    "status": result.status.value,
                    "summary": result.summary,
                },
            )
            if result.status is ToolStatus.ERROR:
                error = result.root_cause or result.summary
        summary = (turn.content or "").strip() or summary
    else:
        if not summary:
            summary = "Sub-agent stopped after reaching max_iterations."

    status = "error" if error else "ok"
    final_payload = {
        "status": status,
        "summary": summary or "Sub-agent completed.",
        "task": task,
        "parent_run": parent_run_id,
        "run_id": run_id,
        "sub_agent_depth": child_depth,
        "iterations": min(
            len([m for m in messages if m.get("role") == "assistant"]),
            max_iterations,
        ),
        "tools": tool_trace,
        "error": error,
    }
    await emit("sub_agent_finished", final_payload)
    return final_payload


def build_sub_agent_handler(
    model: CodingModel,
    workspace_factory: WorkspaceFactory,
    *,
    permission: PermissionMode = PermissionMode.READ_ONLY,
    ops_approved: bool = False,
    network_approved: bool = False,
    tool_allowlist: frozenset[str] | set[str] | None = None,
    max_iterations: int = 5,
    parent_run_id: str | None = None,
    on_event: EventSink | None = None,
    registry: ToolRegistry | None = None,
    approved: bool = False,
    parent_depth: int = 0,
) -> SubAgentHandler:
    """Build a Worker-facing callback with immutable read-only child capabilities."""
    requested = (
        DEFAULT_SUB_AGENT_ALLOWLIST
        if tool_allowlist is None
        else frozenset(tool_allowlist)
    )
    safe_allowlist = frozenset(requested & DEFAULT_SUB_AGENT_ALLOWLIST)

    async def handler(task: str) -> dict[str, Any]:
        return await run_sub_agent(
            task,
            model=model,
            workspace=workspace_factory(),
            permission=PermissionMode.READ_ONLY,
            ops_approved=False,
            network_approved=False,
            tool_allowlist=safe_allowlist,
            max_iterations=max_iterations,
            parent_run_id=parent_run_id,
            on_event=on_event,
            registry=registry,
            approved=False,
            metadata={"sub_agent_depth": parent_depth},
        )

    return handler


async def _emit(
    on_event: EventSink | None,
    *,
    event: str,
    data: dict[str, Any],
    parent_run_id: str | None,
    run_id: str,
    sequence: int,
) -> None:
    if on_event is None:
        return
    payload = {
        "sequence": sequence,
        "run_id": run_id,
        "event": event,
        "sub_agent": True,
        "parent_run": parent_run_id,
        "data": data,
    }
    await on_event(payload)
