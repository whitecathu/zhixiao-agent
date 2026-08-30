from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("textual")

from textual.widgets import Input, RichLog  # noqa: E402

from zhixiao_agent.session_controller import WorkMode  # noqa: E402
from zhixiao_agent.tui import create_app  # noqa: E402
from zhixiao_agent.types import (  # noqa: E402
    PermissionMode,
    RunResult,
    RunStatus,
    TaskType,
    TerminationReason,
    VerificationOutcome,
    VerificationResult,
)


def result(summary: str = "done") -> RunResult:
    return RunResult(
        run_id="pilot-run",
        status=RunStatus.SUCCEEDED,
        summary=summary,
        task_type=TaskType.REVIEW,
        verification=VerificationResult(
            outcome=VerificationOutcome.SKIPPED,
            reason="read-only review",
        ),
        termination_reason=TerminationReason.COMPLETED,
    )


def _log_text(app: Any) -> str:
    return "\n".join(str(line) for line in app.query_one("#log", RichLog).lines)


@pytest.mark.asyncio
async def test_tui_streams_events_and_survives_task_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    app = create_app(workspace=tmp_path, offline=True)
    calls = 0

    async def execute(prompt: str, **kwargs: Any) -> RunResult:
        nonlocal calls
        calls += 1
        on_event = kwargs["on_event"]
        if calls == 1:
            await on_event({"event": "tool_result", "data": {"summary": "read file"}})
            raise RuntimeError("model unavailable")
        return result("second run completed")

    app.execute_local = execute
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt", Input)
        prompt.focus()
        prompt.value = "first"
        await pilot.press("enter")
        await pilot.pause(0.1)
        prompt.value = "second"
        await pilot.press("enter")
        await pilot.pause(0.1)

        lines = _log_text(app)
        assert "tool_result" in lines
        assert "model unavailable" in lines
        assert "second run completed" in lines


@pytest.mark.asyncio
async def test_tui_cancel_stops_background_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    app = create_app(workspace=tmp_path, offline=True)
    cancelled = asyncio.Event()

    async def execute(prompt: str, **kwargs: Any) -> RunResult:
        del prompt, kwargs
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return result()

    app.execute_local = execute
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt", Input)
        prompt.focus()
        prompt.value = "long task"
        await pilot.press("enter")
        await pilot.pause(0.05)
        prompt.value = "/cancel"
        await pilot.press("enter")
        await pilot.pause(0.1)

        assert cancelled.is_set()
        lines = _log_text(app)
        assert "checkpoint remains recoverable" in lines


@pytest.mark.asyncio
async def test_tui_unknown_slash_prints_error_and_does_not_start_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    app = create_app(workspace=tmp_path, offline=True)
    calls = 0

    async def execute(prompt: str, **kwargs: Any) -> RunResult:
        nonlocal calls
        calls += 1
        del prompt, kwargs
        return result()

    app.execute_local = execute
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt", Input)
        prompt.focus()
        prompt.value = "/foo"
        await pilot.press("enter")
        await pilot.pause(0.05)

        lines = _log_text(app)
        assert "Unknown command" in lines
        assert "/help" in lines
        assert calls == 0


@pytest.mark.asyncio
async def test_tui_plugins_lists_builtin_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    app = create_app(workspace=tmp_path, offline=True)
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt", Input)
        prompt.focus()
        prompt.value = "/plugins"
        await pilot.press("enter")
        await pilot.pause(0.05)

        lines = _log_text(app)
        assert "core.tools" in lines
        assert "core.commands" in lines


@pytest.mark.asyncio
async def test_tui_permissions_full_untrusted_stays_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    app = create_app(workspace=tmp_path, offline=True, trust_workspace=False)
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt", Input)
        prompt.focus()
        prompt.value = "/permissions full"
        await pilot.press("enter")
        await pilot.pause(0.05)

        assert app.permission is PermissionMode.READ_ONLY
        lines = _log_text(app)
        assert "--trust-workspace" in lines


@pytest.mark.asyncio
async def test_tui_mode_plan_changes_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    app = create_app(workspace=tmp_path, offline=True)
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt", Input)
        prompt.focus()
        prompt.value = "/mode plan"
        await pilot.press("enter")
        await pilot.pause(0.05)

        assert app.mode is WorkMode.PLAN
        assert "plan" in _log_text(app)


@pytest.mark.asyncio
async def test_tui_busy_enter_queues_next_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    app = create_app(workspace=tmp_path, offline=True)
    started = asyncio.Event()
    release = asyncio.Event()
    prompts: list[str] = []

    async def execute(prompt: str, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        prompts.append(prompt)
        started.set()
        await release.wait()
        return {
            "run_id": f"run-{len(prompts)}",
            "status": "succeeded",
            "summary": f"done {prompt}",
            "plan": [],
        }

    app.execute_local = execute
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt", Input)
        prompt.focus()
        prompt.value = "first"
        await pilot.press("enter")
        await asyncio.wait_for(started.wait(), timeout=2)
        started.clear()
        prompt.value = "second"
        await pilot.press("enter")
        await pilot.pause(0.05)
        lines = _log_text(app)
        assert "Queued next turn" in lines
        assert prompts == ["first"]
        release.set()
        await asyncio.wait_for(started.wait(), timeout=2)
        await pilot.pause(0.1)
        assert prompts == ["first", "second"]


@pytest.mark.asyncio
async def test_tui_fork_calls_fork_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    app = create_app(workspace=tmp_path, offline=True)
    captured: dict[str, Any] = {}

    async def fake_fork(
        run_id: str,
        *,
        settings: Any,
        prompt: str | None = None,
        offline: bool = False,
        on_event: Any = None,
    ) -> dict[str, Any]:
        captured["run_id"] = run_id
        captured["settings"] = settings
        captured["prompt"] = prompt
        captured["offline"] = offline
        if on_event is not None:
            await on_event({"event": "tool_result", "data": {"summary": "forked"}})
        return {
            "run_id": "fork-1",
            "status": "succeeded",
            "summary": "forked ok",
            "plan": [],
        }

    app.fork_local = fake_fork
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt", Input)
        prompt.focus()
        prompt.value = "/fork parent-run"
        await pilot.press("enter")
        await pilot.pause(0.1)

        assert captured["run_id"] == "parent-run"
        assert captured["settings"] is app.settings
        assert "forked ok" in _log_text(app)


@pytest.mark.asyncio
async def test_tui_calls_execute_local_with_workspace_and_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    app = create_app(workspace=tmp_path, offline=True)
    captured: dict[str, Any] = {}

    async def execute(prompt: str, **kwargs: Any) -> dict[str, Any]:
        captured["prompt"] = prompt
        captured.update(kwargs)
        return {
            "run_id": "stored-run",
            "status": "succeeded",
            "summary": "persisted",
            "plan": ["inspect"],
        }

    app.execute_local = execute
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt", Input)
        prompt.focus()
        prompt.value = "ship the feature"
        await pilot.press("enter")
        await pilot.pause(0.1)

        assert captured["prompt"] == "ship the feature"
        assert captured["workspace"] == tmp_path.resolve()
        assert captured["settings"] is app.settings
        assert captured["permission"] is PermissionMode.READ_ONLY
        assert captured["mode"] is WorkMode.ASK
        assert captured["trusted"] is False
        assert "persisted" in _log_text(app)
