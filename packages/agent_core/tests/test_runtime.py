from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from zhixiao_agent.model import CodingModel, ModelTurn, ScriptedModel
from zhixiao_agent.runner import LocalRunner
from zhixiao_agent.runtime import AgentRuntime, RuntimeConfig
from zhixiao_agent.types import (
    PermissionMode,
    RunBudget,
    RunStatus,
    TerminationReason,
    ToolCall,
    VerificationOutcome,
)


@pytest.mark.asyncio
async def test_runtime_plans_uses_tool_and_finishes(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    model = ScriptedModel(
        [
            ModelTurn(content='{"plan":["Read the repository","Report findings"]}'),
            ModelTurn(
                tool_calls=[ToolCall(id="1", name="read_file", arguments={"path": "README.md"})]
            ),
            ModelTurn(content="Repository inspection completed.", model="scripted"),
        ]
    )

    result = await AgentRuntime(model).run(
        "review the project",
        tmp_path,
        RuntimeConfig(permission=PermissionMode.READ_ONLY, require_plan_approval=False),
    )

    assert result.status is RunStatus.SUCCEEDED
    assert result.plan == ["Read the repository", "Report findings"]
    assert any(event.event == "tool_result" for event in result.events)
    assert result.summary == "Repository inspection completed."


@pytest.mark.asyncio
async def test_read_only_run_does_not_package_existing_workspace_diff(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "README.md").write_text("clean\n", encoding="utf-8")
    runner = LocalRunner(repository)
    for command in (
        "git init -b main",
        "git -c user.name=Test -c user.email=test@example.com add .",
        "git -c user.name=Test -c user.email=test@example.com commit -m init",
    ):
        command_result = await runner.run(command, permission=PermissionMode.EXECUTE)
        assert command_result.exit_code == 0, command_result.stderr
    (repository / "README.md").write_text("user change\n", encoding="utf-8")

    result = await AgentRuntime(
        ScriptedModel(
            [
                ModelTurn(content='{"plan":["Inspect only"]}'),
                ModelTurn(content="Read-only inspection completed."),
            ]
        )
    ).run(
        "review the project",
        repository,
        RuntimeConfig(permission=PermissionMode.READ_ONLY, require_plan_approval=False),
    )

    assert result.status is RunStatus.SUCCEEDED
    assert result.diff == ""
    assert not any(item.kind == "git_diff" for item in result.artifacts)


@pytest.mark.asyncio
async def test_edit_run_stops_for_plan_approval(tmp_path: Path) -> None:
    model = ScriptedModel([ModelTurn(content='{"plan":["Edit the file"]}')])

    result = await AgentRuntime(model).run(
        "implement a feature",
        tmp_path,
        RuntimeConfig(permission=PermissionMode.EDIT, require_plan_approval=True),
    )

    assert result.status is RunStatus.AWAITING_APPROVAL
    assert any(event.event == "approval_required" for event in result.events)
    assert not (tmp_path.parent / ".zhixiao-worktrees" / tmp_path.name).exists()


@pytest.mark.asyncio
async def test_runtime_resumes_from_durable_sqlite_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "state"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("durable\n", encoding="utf-8")
    monkeypatch.setenv("ZHIXIAO_STATE_DIR", str(state_dir))
    run_id = "durable-run"
    first = AgentRuntime(ScriptedModel([ModelTurn(content='{"plan":["Inspect the repository"]}')]))
    pending = await first.run(
        "implement a durable feature",
        workspace,
        RuntimeConfig(permission=PermissionMode.EDIT, require_plan_approval=True),
        run_id=run_id,
    )
    assert pending.status is RunStatus.AWAITING_APPROVAL

    restarted = AgentRuntime(
        ScriptedModel([ModelTurn(content="Implementation resumed after approval.")])
    )
    completed = await restarted.resume(
        run_id,
        approved=True,
        config=RuntimeConfig(permission=PermissionMode.EDIT, require_plan_approval=True),
    )
    assert completed.status is RunStatus.SUCCEEDED
    assert completed.summary == "Implementation resumed after approval."
    assert (state_dir / "checkpoints.sqlite3").is_file()


@pytest.mark.asyncio
async def test_edit_run_uses_an_isolated_git_worktree(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "app.py").write_text("value = 1\n", encoding="utf-8")
    runner = LocalRunner(repository)
    for command in (
        "git init -b main",
        "git -c user.name=Test -c user.email=test@example.com add .",
        "git -c user.name=Test -c user.email=test@example.com commit -m init",
    ):
        command_result = await runner.run(command, permission=PermissionMode.EXECUTE)
        assert command_result.exit_code == 0, command_result.stderr
    model = ScriptedModel(
        [
            ModelTurn(content='{"plan":["Edit app.py"]}'),
            ModelTurn(
                tool_calls=[
                    ToolCall(
                        id="edit",
                        name="exact_edit",
                        arguments={
                            "path": "app.py",
                            "old_text": "value = 1",
                            "new_text": "value = 2",
                        },
                    )
                ]
            ),
            ModelTurn(content="Updated app.py in the isolated worktree."),
        ]
    )
    result = await AgentRuntime(model).run(
        "implement a value change",
        repository,
        RuntimeConfig(
            permission=PermissionMode.FULL,
            require_plan_approval=True,
            approved=True,
            allow_unverified="fixture has no automated test suite",
        ),
        run_id="worktree-test",
    )
    assert result.status is RunStatus.SUCCEEDED
    assert (repository / "app.py").read_text(encoding="utf-8") == "value = 1\n"
    worktree = next(item for item in result.artifacts if item.kind == "worktree")
    assert (Path(worktree.path) / "app.py").read_text(encoding="utf-8") == "value = 2\n"
    assert worktree.base_sha
    created = next(event for event in result.events if event.event == "worktree_created")
    assert created.data["repository"] == str(repository.resolve())
    assert created.data["base_sha"] == worktree.base_sha
    assert created.data["branch"] == "zhixiao/worktree-test"
    assert "value = 2" in result.diff


@pytest.mark.asyncio
async def test_on_event_keeps_firing_after_state_event_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Truncating state.events must not stall the live on_event fan-out."""
    import zhixiao_agent.runtime as runtime_module

    monkeypatch.setattr(runtime_module, "_MAX_EVENTS_IN_STATE", 3)
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")
    (tmp_path / "c.txt").write_text("c\n", encoding="utf-8")
    (tmp_path / "d.txt").write_text("d\n", encoding="utf-8")
    model = ScriptedModel(
        [
            ModelTurn(content='{"plan":["Read files"]}'),
            ModelTurn(
                tool_calls=[
                    ToolCall(id="1", name="read_file", arguments={"path": "a.txt"}),
                    ToolCall(id="2", name="read_file", arguments={"path": "b.txt"}),
                    ToolCall(id="3", name="read_file", arguments={"path": "c.txt"}),
                    ToolCall(id="4", name="read_file", arguments={"path": "d.txt"}),
                ]
            ),
            ModelTurn(content="Read four files.", model="scripted"),
        ]
    )
    seen: list[int] = []

    async def on_event(event: dict) -> None:
        seen.append(int(event["sequence"]))

    result = await AgentRuntime(model).run(
        "review the project",
        tmp_path,
        RuntimeConfig(
            permission=PermissionMode.READ_ONLY,
            require_plan_approval=False,
            on_event=on_event,
        ),
    )

    assert result.status is RunStatus.SUCCEEDED
    assert seen == sorted(seen)
    assert max(seen) >= 4
    assert len(seen) == len(set(seen))
    # Cap keeps only the latest window in durable state, but live sink saw more.
    assert len(result.events) <= 3
    assert len(seen) > len(result.events)


@pytest.mark.asyncio
async def test_write_run_cannot_succeed_when_verification_is_blocked(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            ModelTurn(content='{"plan":["Write a file"]}'),
            ModelTurn(
                tool_calls=[
                    ToolCall(
                        id="write",
                        name="write_file",
                        arguments={"path": "feature.txt", "content": "done\n"},
                    )
                ]
            ),
            ModelTurn(content="Implemented feature."),
        ]
    )
    result = await AgentRuntime(model).run(
        "implement a feature",
        tmp_path,
        RuntimeConfig(
            permission=PermissionMode.EDIT,
            require_plan_approval=False,
            isolate_worktree=False,
        ),
    )

    assert result.status is RunStatus.FAILED
    assert result.verification.outcome is VerificationOutcome.BLOCKED
    assert result.termination_reason is TerminationReason.VERIFICATION_BLOCKED


@pytest.mark.asyncio
async def test_explicit_waiver_allows_unverified_write(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            ModelTurn(content='{"plan":["Write a file"]}'),
            ModelTurn(
                tool_calls=[
                    ToolCall(
                        id="write",
                        name="write_file",
                        arguments={"path": "feature.txt", "content": "done\n"},
                    )
                ]
            ),
            ModelTurn(content="Implemented feature."),
        ]
    )
    result = await AgentRuntime(model).run(
        "implement a feature",
        tmp_path,
        RuntimeConfig(
            permission=PermissionMode.EDIT,
            require_plan_approval=False,
            isolate_worktree=False,
            allow_unverified="fixture intentionally has no test runner",
        ),
    )

    assert result.status is RunStatus.SUCCEEDED
    assert result.verification.outcome is VerificationOutcome.SKIPPED
    assert result.verification.waived is True


@pytest.mark.asyncio
async def test_model_turn_budget_stops_tool_loop_with_structured_reason(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            ModelTurn(content='{"plan":["Inspect repeatedly"]}'),
            ModelTurn(
                tool_calls=[ToolCall(id="one", name="list_directory", arguments={"path": "."})]
            ),
        ]
    )
    result = await AgentRuntime(model).run(
        "review the project",
        tmp_path,
        RuntimeConfig(
            permission=PermissionMode.READ_ONLY,
            require_plan_approval=False,
            budget=RunBudget(max_model_turns=2),
        ),
    )

    assert result.status is RunStatus.FAILED
    assert result.termination_reason is TerminationReason.BUDGET_EXHAUSTED
    assert result.usage.model_turns == 2


@pytest.mark.asyncio
async def test_write_run_patch_includes_untracked_file_and_metadata(tmp_path: Path) -> None:
    runner = LocalRunner(tmp_path)
    for command in (
        "git init -b main",
        "git -c user.name=Test -c user.email=test@example.com commit --allow-empty -m init",
    ):
        command_result = await runner.run(command, permission=PermissionMode.EXECUTE)
        assert command_result.exit_code == 0, command_result.stderr
    model = ScriptedModel(
        [
            ModelTurn(content='{"plan":["Create a file"]}'),
            ModelTurn(
                tool_calls=[
                    ToolCall(
                        id="write",
                        name="write_file",
                        arguments={"path": "new.txt", "content": "hello\n"},
                    )
                ]
            ),
            ModelTurn(content="Created file."),
        ]
    )
    result = await AgentRuntime(model).run(
        "implement a file",
        tmp_path,
        RuntimeConfig(
            permission=PermissionMode.FULL,
            require_plan_approval=False,
            isolate_worktree=False,
            allow_unverified="no test suite in fixture",
        ),
    )

    assert "new.txt" in result.diff
    patch = next(item for item in result.artifacts if item.kind == "git_diff")
    assert Path(patch.path).read_text(encoding="utf-8") == result.diff
    assert patch.sha256 and patch.size_bytes and patch.base_sha


@pytest.mark.asyncio
async def test_dirty_source_repository_is_blocked_before_worktree(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    runner = LocalRunner(repository)
    for command in (
        "git init -b main",
        "git -c user.name=Test -c user.email=test@example.com commit --allow-empty -m init",
    ):
        command_result = await runner.run(command, permission=PermissionMode.EXECUTE)
        assert command_result.exit_code == 0, command_result.stderr
    (repository / "dirty.txt").write_text("user work\n", encoding="utf-8")
    result = await AgentRuntime(
        ScriptedModel([ModelTurn(content='{"plan":["Edit safely"]}')])
    ).run(
        "implement a safe change",
        repository,
        RuntimeConfig(
            permission=PermissionMode.EDIT,
            require_plan_approval=False,
        ),
    )

    assert result.status is RunStatus.FAILED
    assert result.termination_reason is TerminationReason.RUNTIME_ERROR
    assert "dirty.txt" in (result.error or "")
    assert not any(item.kind == "worktree" for item in result.artifacts)


@pytest.mark.asyncio
async def test_cooperative_stop_file_interrupts_tool_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "state"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("hello\n", encoding="utf-8")
    monkeypatch.setenv("ZHIXIAO_STATE_DIR", str(state_dir))
    run_id = "interrupt-loop"

    class StopOnSecondComplete(CodingModel):
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
                stop = Path(state_dir).expanduser().resolve() / "control" / run_id
                stop.parent.mkdir(parents=True, exist_ok=True)
                stop.write_text("interrupt\n", encoding="utf-8")
            if self.calls == 1:
                return ModelTurn(content='{"plan":["Read the repository repeatedly"]}')
            return ModelTurn(
                tool_calls=[
                    ToolCall(
                        id=f"read-{self.calls}",
                        name="read_file",
                        arguments={"path": "README.md"},
                    )
                ]
            )

    result = await AgentRuntime(StopOnSecondComplete()).run(
        "review the project",
        workspace,
        RuntimeConfig(
            permission=PermissionMode.READ_ONLY,
            require_plan_approval=False,
            state_dir=state_dir,
        ),
        run_id=run_id,
    )

    assert result.status is RunStatus.INTERRUPTED
    assert result.termination_reason is TerminationReason.INTERRUPTED
    assert "interrupted" in result.summary.lower()
    assert any(event.event == "run_interrupted" for event in result.events)
    assert not (Path(state_dir).expanduser().resolve() / "control" / run_id).exists()


@pytest.mark.asyncio
async def test_cooperative_stop_resume_continues_same_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "state"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("hello\n", encoding="utf-8")
    monkeypatch.setenv("ZHIXIAO_STATE_DIR", str(state_dir))
    run_id = "interrupt-resume"

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
                stop = Path(state_dir).expanduser().resolve() / "control" / run_id
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

    model = StopThenFinish()
    runtime = AgentRuntime(model)
    config = RuntimeConfig(
        permission=PermissionMode.READ_ONLY,
        require_plan_approval=False,
        isolate_worktree=False,
        state_dir=state_dir,
        allow_unverified="resume after cooperative stop has no test suite",
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
    assert not (Path(state_dir).expanduser().resolve() / "control" / run_id).exists()

    completed = await runtime.resume(run_id, approved=True, config=config)

    assert completed.run_id == run_id
    assert completed.status is RunStatus.SUCCEEDED
    assert completed.summary == "Resumed after operator stop."
