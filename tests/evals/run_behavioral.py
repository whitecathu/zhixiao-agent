"""Behavioral evaluation gates that actually run AgentRuntime.

Offline quality here comes from ScriptedModel + AgentRuntime (and the same
interrupt/resume APIs the CLI uses). The checked-in fixture
``tests/evals/fixtures/offline_harness_results.json`` is not a quality score;
it remains provenance for ``--validate-only`` / summarize_results tests.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from zhixiao_agent.model import CodingModel, ModelTurn, ScriptedModel
from zhixiao_agent.runner import LocalRunner
from zhixiao_agent.runtime import AgentRuntime, RuntimeConfig
from zhixiao_agent.tools.registry import READ_ONLY_TOOLS
from zhixiao_agent.types import PermissionMode, RunStatus, TerminationReason, ToolCall, ToolStatus

ROOT = Path(__file__).resolve().parent
REPORT_PATH = ROOT / "artifacts" / "behavioral_report.json"
_WRITE_TOOLS = frozenset(
    {"write_file", "exact_edit", "terminal", "run_tests", "background_command"}
)
_BLOCKED_STATUSES = {ToolStatus.ERROR.value, ToolStatus.BLOCKED.value}


class RecordingModel(ScriptedModel):
    def __init__(self, turns: list[ModelTurn]) -> None:
        super().__init__(turns)
        self.advertised: list[set[str]] = []

    async def complete(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelTurn:
        if tools is not None:
            names = {
                str(item.get("function", {}).get("name") or "")
                for item in tools
                if isinstance(item, dict)
            }
            self.advertised.append({name for name in names if name})
        return await super().complete(messages, tools=tools)


@contextmanager
def _isolated_state_dir(path: Path) -> Iterator[None]:
    previous = os.environ.get("ZHIXIAO_STATE_DIR")
    os.environ["ZHIXIAO_STATE_DIR"] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("ZHIXIAO_STATE_DIR", None)
        else:
            os.environ["ZHIXIAO_STATE_DIR"] = previous


def _runtime_config(**overrides: Any) -> RuntimeConfig:
    values: dict[str, Any] = {
        "permission": PermissionMode.FULL,
        "approved": False,
        "ops_approved": False,
        "ops_capabilities": frozenset(),
        "require_plan_approval": False,
        "isolate_worktree": False,
    }
    values.update(overrides)
    return RuntimeConfig(**values)


def _tool_results(result: Any, tool: str) -> list[Any]:
    return [
        event
        for event in result.events
        if event.event == "tool_result" and event.data.get("tool") == tool
    ]


async def _git(workspace: Path, command: str) -> None:
    result = await LocalRunner(workspace).run(command, permission=PermissionMode.EXECUTE)
    assert result.exit_code == 0, result.stderr or result.stdout


def eval_dangerous_command() -> None:
    """FULL permission without ops capabilities must block push/rm before subprocess."""

    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / "state"
            workspace = root / "repo"
            remote = root / "origin.git"
            workspace.mkdir()
            (workspace / "keep.txt").write_text("must-remain\n", encoding="utf-8")
            doomed = workspace / "doomed"
            doomed.mkdir()
            (doomed / "file.txt").write_text("must-remain\n", encoding="utf-8")
            await _git(workspace, "git init -b main")
            await _git(
                workspace,
                "git -c user.name=Test -c user.email=test@example.com add .",
            )
            await _git(
                workspace,
                "git -c user.name=Test -c user.email=test@example.com commit -m init",
            )
            await _git(root, "git init --bare origin.git")
            await _git(workspace, f"git remote add origin {remote.as_posix()}")
            head = await LocalRunner(workspace).run(
                "git rev-parse HEAD", permission=PermissionMode.EXECUTE
            )
            assert head.exit_code == 0, head.stderr
            head_before = head.stdout.strip()

            model = ScriptedModel(
                [
                    ModelTurn(content='{"plan":["Inspect then run maintenance commands"]}'),
                    ModelTurn(
                        tool_calls=[
                            ToolCall(
                                id="push",
                                name="terminal",
                                arguments={"command": "git push origin main"},
                            ),
                            ToolCall(
                                id="rm",
                                name="terminal",
                                arguments={"command": "rm -rf /tmp/x"},
                            ),
                            ToolCall(
                                id="rm-workspace",
                                name="terminal",
                                arguments={"command": "rm -rf doomed"},
                            ),
                        ]
                    ),
                    ModelTurn(content="Dangerous commands were not executed."),
                ]
            )
            with _isolated_state_dir(state_dir):
                result = await AgentRuntime(model).run(
                    "implement a repository maintenance feature",
                    workspace,
                    _runtime_config(
                        state_dir=state_dir,
                        allow_unverified="dangerous-command gate must not execute git push or rm",
                    ),
                )

            terminal_events = _tool_results(result, "terminal")
            assert len(terminal_events) >= 2, "expected terminal tool results for push and rm"
            for event in terminal_events:
                status = event.data.get("status")
                assert status in _BLOCKED_STATUSES, f"expected blocked terminal, got {status}"
                payload = event.data.get("result") or {}
                cause = str(payload.get("root_cause") or event.data.get("summary") or "")
                assert "approval" in cause.lower() or "permission" in cause.lower(), cause

            assert (workspace / "keep.txt").read_text(encoding="utf-8") == "must-remain\n"
            assert (doomed / "file.txt").read_text(encoding="utf-8") == "must-remain\n"
            head_after = await LocalRunner(workspace).run(
                "git rev-parse HEAD", permission=PermissionMode.EXECUTE
            )
            assert head_after.exit_code == 0, head_after.stderr
            assert head_after.stdout.strip() == head_before
            remote_log = await LocalRunner(root).run(
                "git --git-dir origin.git log --oneline",
                permission=PermissionMode.EXECUTE,
            )
            assert remote_log.exit_code != 0 or not remote_log.stdout.strip()

    asyncio.run(_run())


def eval_interrupt_resume() -> None:
    """Stop file must pause via LangGraph interrupt so the same run_id can resume."""

    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / "state"
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "README.md").write_text("hello\n", encoding="utf-8")
            run_id = "eval-interrupt-resume"

            class StopThenFinish(CodingModel):
                def __init__(self) -> None:
                    self.calls = 0

                async def complete(
                    self,
                    messages: Sequence[dict[str, Any]],
                    *,
                    tools: list[dict[str, Any]] | None = None,
                ) -> ModelTurn:
                    del messages, tools
                    self.calls += 1
                    if self.calls == 2:
                        stop = state_dir.expanduser().resolve() / "control" / run_id
                        stop.parent.mkdir(parents=True, exist_ok=True)
                        stop.write_text("interrupt\n", encoding="utf-8")
                    if self.calls == 1:
                        return ModelTurn(content='{"plan":["Read the repository then finish"]}')
                    if self.calls == 2:
                        return ModelTurn(
                            tool_calls=[
                                ToolCall(
                                    id="read-before-stop",
                                    name="read_file",
                                    arguments={"path": "README.md"},
                                )
                            ]
                        )
                    return ModelTurn(content="Resumed after operator stop.")

            with _isolated_state_dir(state_dir):
                model = StopThenFinish()
                runtime = AgentRuntime(model)
                config = _runtime_config(
                    permission=PermissionMode.READ_ONLY,
                    state_dir=state_dir,
                    allow_unverified="interrupt-resume gate has no test suite",
                )
                pending = await runtime.run(
                    "review the project",
                    workspace,
                    config,
                    run_id=run_id,
                )
                assert pending.status is RunStatus.INTERRUPTED
                assert pending.run_id == run_id
                assert pending.termination_reason is TerminationReason.INTERRUPTED
                assert any(event.event == "run_interrupted" for event in pending.events)
                assert not (state_dir.expanduser().resolve() / "control" / run_id).exists()

                completed = await runtime.resume(run_id, approved=True, config=config)
                assert completed.run_id == run_id
                assert completed.status is RunStatus.SUCCEEDED
                assert completed.summary == "Resumed after operator stop."

    asyncio.run(_run())


def eval_ask_read_only() -> None:
    """ask mode must advertise only read-only tools even with EDIT permission."""

    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            state_dir = workspace / "state"
            (workspace / "README.md").write_text("hello\n", encoding="utf-8")
            model = RecordingModel(
                [
                    ModelTurn(content='{"plan":["Inspect then implement"]}'),
                    ModelTurn(
                        tool_calls=[
                            ToolCall(
                                id="write",
                                name="write_file",
                                arguments={"path": "feature.txt", "content": "done\n"},
                            )
                        ]
                    ),
                    ModelTurn(content="Inspection complete."),
                ]
            )
            with _isolated_state_dir(state_dir):
                result = await AgentRuntime(model).run(
                    "implement a feature",
                    workspace,
                    _runtime_config(
                        permission=PermissionMode.EDIT,
                        mode="ask",
                        state_dir=state_dir,
                        allow_unverified="ask mode must not mutate the workspace",
                    ),
                )
            assert result.status is RunStatus.SUCCEEDED
            assert model.advertised, "ask mode never advertised tools to the model"
            advertised = set.union(*model.advertised)
            assert advertised <= READ_ONLY_TOOLS, advertised
            assert advertised.isdisjoint(_WRITE_TOOLS), advertised
            write_events = _tool_results(result, "write_file")
            assert write_events
            assert write_events[0].data["status"] in _BLOCKED_STATUSES
            assert not (workspace / "feature.txt").exists()

    asyncio.run(_run())


GATES: tuple[tuple[str, Callable[[], None]], ...] = (
    ("dangerous-command", eval_dangerous_command),
    ("interrupt-resume", eval_interrupt_resume),
    ("ask-read-only", eval_ask_read_only),
)


def run_gates() -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for gate_id, fn in GATES:
        try:
            fn()
            results.append({"id": gate_id, "passed": True})
        except Exception as exc:
            results.append(
                {
                    "id": gate_id,
                    "passed": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    passed = all(item["passed"] for item in results)
    return {
        "status": "behavioral",
        "evaluation_mode": "scripted_agent_runtime",
        "metrics_source": "agent_runtime",
        "passed": passed,
        "gates": results,
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    report = run_gates()
    write_report(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
