from pathlib import Path

import pytest

from zhixiao_agent.model import ModelTurn, ScriptedModel
from zhixiao_agent.runner import LocalRunner
from zhixiao_agent.runtime import AgentRuntime, RuntimeConfig
from zhixiao_agent.types import PermissionMode, RunStatus, ToolCall


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
async def test_edit_run_stops_for_plan_approval(tmp_path: Path) -> None:
    model = ScriptedModel([ModelTurn(content='{"plan":["Edit the file"]}')])

    result = await AgentRuntime(model).run(
        "implement a feature",
        tmp_path,
        RuntimeConfig(permission=PermissionMode.EDIT, require_plan_approval=True),
    )

    assert result.status is RunStatus.AWAITING_APPROVAL
    assert any(event.event == "approval_required" for event in result.events)


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
        ),
        run_id="worktree-test",
    )
    assert result.status is RunStatus.SUCCEEDED
    assert (repository / "app.py").read_text(encoding="utf-8") == "value = 1\n"
    worktree = next(item for item in result.artifacts if item.kind == "worktree")
    assert (Path(worktree.path) / "app.py").read_text(encoding="utf-8") == "value = 2\n"
    assert "value = 2" in result.diff
