"""MetaGPT Team runtime that emits LangGraph-compatible run events."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field, PrivateAttr

from .context_compact import maybe_compact_messages
from .metagpt import ActionOutput, BaseRole, Team
from .model import CodingModel
from .runner import LocalRunner
from .skills import SkillManager, default_skill_roots, render_skill_context
from .tools import ToolContext, ToolRegistry, build_default_registry
from .tools.registry import READ_ONLY_TOOLS
from .types import (
    AgentEvent,
    PermissionMode,
    RunBudget,
    RunResult,
    RunStatus,
    RunUsage,
    TaskType,
    TerminationReason,
    ToolResult,
    ToolStatus,
    VerificationOutcome,
    VerificationResult,
    VerificationStage,
)

EventSink = Callable[[dict[str, Any]], Awaitable[None]]
_MAX_TOOL_RESULT_CHARS = 4_000


class LlmToolRole(BaseRole):
    """Single LLM-backed role that may call an allowlisted tool set."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    llm: Any = None
    tool_registry: Any = None
    workspace_path: str = ""
    permission: PermissionMode = PermissionMode.READ_ONLY
    approved: bool = False
    ops_approved: bool = False
    ops_capabilities: frozenset[str] = Field(default_factory=frozenset)
    network_approved: bool = False
    network_capabilities: frozenset[str] = Field(default_factory=frozenset)
    run_id: str = ""
    max_tool_iterations: int = 5
    tool_metadata: dict[str, Any] = Field(default_factory=dict)
    _on_event: EventSink | None = PrivateAttr(default=None)
    _events: list[dict[str, Any]] = PrivateAttr(default_factory=list)
    _sequence: int = PrivateAttr(default=0)

    def bind_events(
        self,
        events: list[dict[str, Any]],
        sequence: int,
        on_event: EventSink | None,
    ) -> None:
        self._events = events
        self._sequence = sequence
        self._on_event = on_event

    @property
    def sequence(self) -> int:
        return self._sequence

    async def _emit(self, event: str, data: dict[str, Any]) -> None:
        last_sequence = int(self._events[-1]["sequence"]) if self._events else 0
        self._sequence = max(self._sequence, last_sequence) + 1
        payload = {
            "sequence": self._sequence,
            "run_id": self.run_id,
            "event": event,
            "data": data,
        }
        self._events.append(payload)
        if self._on_event is not None:
            await self._on_event(payload)

    async def _think(self) -> bool:
        return True

    async def _act(self) -> ActionOutput:
        assert self.llm is not None and self.tool_registry is not None and self.workspace_path
        workspace = Path(self.workspace_path)
        message = self.state.get("last_message")
        prompt = str(message.content) if message is not None else self.goal
        skills = SkillManager(default_skill_roots(workspace))
        skills.load()
        skill_context = render_skill_context(prompt, skills)
        system = (
            f"You are {self.name} ({self.profile}). Goal: {self.goal}.\n"
            "Use tools when needed, then answer with a concise summary."
        )
        if skill_context:
            system = f"{system}\n\n{skill_context}"
        requested = set(self.tools) if self.tools else set(READ_ONLY_TOOLS)
        allowed = requested & self.tool_registry.names()
        context = ToolContext(
            workspace=workspace,
            permission=self.permission,
            runner=LocalRunner(workspace),
            approved=self.approved,
            ops_approved=self.ops_approved,
            ops_capabilities=frozenset(self.ops_capabilities),
            network_approved=self.network_approved,
            network_capabilities=frozenset(self.network_capabilities),
            metadata=dict(self.tool_metadata),
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        await self._emit("workflow_node_started", {"node_id": self.name, "role": self.profile})
        summaries: list[str] = []
        failed = False
        failure_reason: str | None = None
        final = ""
        exhausted = True
        for iteration in range(max(1, self.max_tool_iterations)):
            messages = maybe_compact_messages(messages)
            try:
                turn = await self.llm.complete(
                    messages,
                    tools=self.tool_registry.schemas(allowed),
                )
            except Exception as exc:
                failed = True
                failure_reason = str(exc)
                await self._emit(
                    "model_turn",
                    {
                        "model": "",
                        "tool_calls": [],
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "cost_usd": 0.0,
                        "content": "",
                        "iteration": iteration + 1,
                        "failed": True,
                        "error": failure_reason,
                    },
                )
                exhausted = False
                break

            tool_calls_formatted = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in turn.tool_calls
            ]
            messages.append(
                {
                    "role": "assistant",
                    "content": turn.content,
                    "tool_calls": tool_calls_formatted,
                }
            )
            await self._emit(
                "model_turn",
                {
                    "model": turn.model,
                    "tool_calls": [call.name for call in turn.tool_calls],
                    "prompt_tokens": turn.prompt_tokens,
                    "completion_tokens": turn.completion_tokens,
                    "cost_usd": turn.cost_usd,
                    "content": (turn.content or "")[:2_000],
                    "iteration": iteration + 1,
                },
            )
            if turn.content.strip():
                final = turn.content.strip()
            if not turn.tool_calls:
                exhausted = False
                break

            for call in turn.tool_calls:
                try:
                    result = await self.tool_registry.execute(
                        call.name,
                        call.arguments,
                        context,
                        allowed=allowed,
                    )
                except Exception as exc:
                    result = ToolResult.error(
                        "tool execution failed",
                        root_cause=str(exc),
                        retry="inspect the tool arguments before retrying",
                    )
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
                await self._emit(
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
                summaries.append(f"{call.name}: {result.summary}")
                if result.status is ToolStatus.ERROR:
                    failed = True
                    failure_reason = result.root_cause or result.summary

        if exhausted:
            failed = True
            failure_reason = "maximum tool iterations reached"
        final = final or "; ".join(summaries) or failure_reason or f"{self.name} completed"
        await self._emit(
            "workflow_node_finished",
            {
                "node_id": self.name,
                "role": self.profile,
                "failed": failed,
                "error": failure_reason,
            },
        )
        return ActionOutput(
            result=final,
            is_success=not failed,
            metadata={"role": self.name, "error": failure_reason},
        )


async def run_metagpt_team(
    prompt: str,
    workspace: Path,
    *,
    model: CodingModel,
    permission: PermissionMode = PermissionMode.READ_ONLY,
    approved: bool = False,
    ops_approved: bool = False,
    ops_capabilities: frozenset[str] | set[str] | None = None,
    network_approved: bool = False,
    network_capabilities: frozenset[str] | set[str] | None = None,
    roles_json: str = "",
    run_id: str | None = None,
    on_event: EventSink | None = None,
    registry: ToolRegistry | None = None,
    max_iterations: int = 6,
    max_tool_iterations: int = 5,
    tool_metadata: dict[str, Any] | None = None,
    budget: RunBudget | None = None,
    allow_unverified: str | None = None,
    verification_commands: tuple[str, ...] = (),
) -> RunResult:
    """Execute an opt-in MetaGPT Team and return a RunResult-shaped payload."""
    rid = run_id or uuid.uuid4().hex
    tools = registry or build_default_registry()
    role_specs = _parse_roles(roles_json)
    events: list[dict[str, Any]] = []
    run_budget = budget or RunBudget()
    started_at = time.monotonic()

    async def emit(event: str, data: dict[str, Any]) -> None:
        sequence = (events[-1]["sequence"] + 1) if events else 1
        payload = {"sequence": sequence, "run_id": rid, "event": event, "data": data}
        events.append(payload)
        if on_event is not None:
            await on_event(payload)

    await emit(
        "run_started",
        {"task_type": TaskType.FEATURE.value, "agents": [spec["name"] for spec in role_specs]},
    )
    team = Team()
    hired: list[LlmToolRole] = []
    for spec in role_specs:
        role = LlmToolRole(
            name=spec["name"],
            profile=spec.get("profile") or spec.get("role") or "implementer",
            goal=spec.get("goal") or prompt,
            tools=list(spec.get("tools") or []),
            watch=list(spec.get("watch") or []),
            llm=model,
            tool_registry=tools,
            workspace_path=str(workspace),
            permission=permission,
            approved=approved,
            ops_approved=ops_approved,
            ops_capabilities=frozenset(ops_capabilities or ()),
            network_approved=network_approved,
            network_capabilities=frozenset(network_capabilities or ()),
            run_id=rid,
            max_tool_iterations=max_tool_iterations,
            tool_metadata=dict(tool_metadata or {}),
        )
        role.bind_events(events, events[-1]["sequence"] if events else 0, on_event)
        hired.append(role)
        team.hire([role])

    if (
        permission is not PermissionMode.READ_ONLY
        and not verification_commands
        and not allow_unverified
    ):
        await emit(
            "verification_skipped",
            {
                "outcome": VerificationOutcome.BLOCKED.value,
                "reason": "write-mode MetaGPT run requires verification or an explicit waiver",
            },
        )
        await emit(
            "run_finished",
            {
                "status": RunStatus.FAILED.value,
                "termination_reason": TerminationReason.VERIFICATION_BLOCKED.value,
            },
        )
        return RunResult(
            run_id=rid,
            status=RunStatus.FAILED,
            summary="MetaGPT write run was blocked before execution.",
            task_type=TaskType.FEATURE,
            plan=[f"MetaGPT role: {role.name}" for role in hired],
            events=[AgentEvent.model_validate(event) for event in events],
            verification=VerificationResult(
                outcome=VerificationOutcome.BLOCKED,
                reason="write-mode MetaGPT run requires verification or an explicit waiver",
            ),
            termination_reason=TerminationReason.VERIFICATION_BLOCKED,
            budgets=run_budget,
            next_actions=["provide verification_commands or an explicit waiver"],
        )

    try:
        results = await team.run(prompt, max_iterations=max_iterations)
    except Exception as exc:
        await emit(
            "error",
            {"message": str(exc), "phase": "metagpt_team"},
        )
        await emit("run_finished", {"status": RunStatus.FAILED.value})
        return RunResult(
            run_id=rid,
            status=RunStatus.FAILED,
            summary="MetaGPT team failed.",
            task_type=TaskType.FEATURE,
            plan=[f"MetaGPT role: {role.name}" for role in hired],
            artifacts=[],
            test_command=None,
            test_exit_code=None,
            diff="",
            events=[AgentEvent.model_validate(event) for event in events],
            error=str(exc),
            termination_reason=TerminationReason.MODEL_ERROR,
            budgets=run_budget,
            next_actions=["inspect the MetaGPT model failure and retry"],
        )
    summary_parts = [f"{name}: {out.result}" for name, out in results.items()]
    success = all(out.is_success for out in results.values()) if results else True
    model_events = [event for event in events if event["event"] == "model_turn"]
    tool_events = [event for event in events if event["event"] == "tool_result"]
    usage = RunUsage(
        model_turns=len(model_events),
        tool_calls=len(tool_events),
        prompt_tokens=sum(int(event["data"].get("prompt_tokens") or 0) for event in model_events),
        completion_tokens=sum(
            int(event["data"].get("completion_tokens") or 0) for event in model_events
        ),
        cost_usd=sum(float(event["data"].get("cost_usd") or 0) for event in model_events),
        elapsed_seconds=max(time.monotonic() - started_at, 0.0),
    )
    budget_reason: str | None = None
    if usage.model_turns > run_budget.max_model_turns:
        budget_reason = f"model turn budget exhausted ({run_budget.max_model_turns})"
    elif usage.tool_calls > run_budget.max_tool_calls:
        budget_reason = f"tool call budget exhausted ({run_budget.max_tool_calls})"
    elif usage.prompt_tokens + usage.completion_tokens > run_budget.max_tokens:
        budget_reason = f"token budget exhausted ({run_budget.max_tokens})"
    elif run_budget.max_cost_usd is not None and usage.cost_usd > run_budget.max_cost_usd:
        budget_reason = f"cost budget exhausted (${run_budget.max_cost_usd:.4f})"
    elif usage.elapsed_seconds > run_budget.max_duration_seconds:
        budget_reason = f"duration budget exhausted ({run_budget.max_duration_seconds}s)"
    if budget_reason:
        success = False
    stages: list[VerificationStage] = []
    verification = VerificationResult(
        outcome=VerificationOutcome.SKIPPED,
        reason=(
            "read-only run does not require executable verification"
            if permission is PermissionMode.READ_ONLY
            else "verification explicitly waived"
        ),
        waived=permission is not PermissionMode.READ_ONLY and bool(allow_unverified),
        waiver_reason=allow_unverified,
    )
    test_exit_code: int | None = None
    failure_reason: str | None = None
    if success and verification_commands:
        context = ToolContext(
            workspace=workspace,
            permission=permission,
            runner=LocalRunner(workspace),
            approved=approved,
        )
        for index, command in enumerate(verification_commands):
            result = await tools.execute(
                "run_tests",
                {"command": command},
                context,
                allowed={"run_tests"},
            )
            test_exit_code = (
                (result.data or {}).get("exit_code")
                if isinstance(result.data, dict)
                else None
            )
            outcome = (
                VerificationOutcome.PASSED
                if result.status is ToolStatus.SUCCESS and test_exit_code == 0
                else VerificationOutcome.FAILED
            )
            stages.append(
                VerificationStage(
                    name="focused" if index == 0 else f"stage_{index + 1}",
                    command=command,
                    outcome=outcome,
                    exit_code=test_exit_code,
                    summary=result.summary,
                    artifacts=result.artifacts,
                )
            )
            await emit(
                "verification_finished",
                {
                    "stage": stages[-1].name,
                    "command": command,
                    "exit_code": test_exit_code,
                    "status": result.status.value,
                },
            )
            if outcome is VerificationOutcome.FAILED:
                success = False
                failure_reason = result.root_cause or result.summary
                break
        verification = VerificationResult(
            outcome=(
                VerificationOutcome.PASSED if success else VerificationOutcome.FAILED
            ),
            reason=(
                "all required verification stages passed"
                if success
                else failure_reason or "verification failed"
            ),
            stages=stages,
        )
    await emit(
        "run_finished",
        {
            "status": "succeeded" if success else "failed",
            "termination_reason": (
                TerminationReason.COMPLETED.value
                if success
                else TerminationReason.BUDGET_EXHAUSTED.value
                if budget_reason
                else TerminationReason.VERIFICATION_FAILED.value
                if verification.outcome is VerificationOutcome.FAILED
                else TerminationReason.RUNTIME_ERROR.value
            ),
        },
    )
    return RunResult(
        run_id=rid,
        status=RunStatus.SUCCEEDED if success else RunStatus.FAILED,
        summary="\n".join(summary_parts) or "MetaGPT team finished.",
        task_type=TaskType.FEATURE,
        plan=[f"MetaGPT role: {name}" for name in results],
        artifacts=[],
        test_command=None,
        test_exit_code=test_exit_code,
        diff="",
        events=[AgentEvent.model_validate(event) for event in events],
        error=None if success else budget_reason or failure_reason or "one or more roles failed",
        verification=verification,
        termination_reason=(
            TerminationReason.COMPLETED
            if success
            else TerminationReason.BUDGET_EXHAUSTED
            if budget_reason
            else TerminationReason.VERIFICATION_FAILED
            if verification.outcome is VerificationOutcome.FAILED
            else TerminationReason.RUNTIME_ERROR
        ),
        usage=usage,
        budgets=run_budget,
        next_actions=(
            []
            if success
            else ["increase the relevant run budget after reviewing usage"]
            if budget_reason
            else ["inspect the failed role or verification stage"]
        ),
    )


def _parse_roles(roles_json: str) -> list[dict[str, Any]]:
    if roles_json.strip():
        try:
            payload = json.loads(roles_json)
            if isinstance(payload, list) and payload:
                return [item for item in payload if isinstance(item, dict) and item.get("name")]
        except json.JSONDecodeError:
            pass
    return [
        {
            "name": "explorer",
            "profile": "explorer",
            "goal": "Inspect the workspace and report findings",
            "tools": ["list_directory", "read_file", "grep", "git_status"],
            "watch": [],
        }
    ]
