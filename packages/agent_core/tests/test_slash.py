from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from zhixiao_agent.extensions import McpConfigStore, McpServer
from zhixiao_agent.session_controller import WorkMode
from zhixiao_agent.slash import (
    BUILTIN_COMMANDS,
    HELP,
    REVIEW_PROMPT,
    SlashContext,
    dispatch_slash,
)
from zhixiao_agent.types import (
    PermissionMode,
    RunResult,
    RunStatus,
    TaskType,
    VerificationOutcome,
    VerificationResult,
)


def _ctx(tmp_path: Path, **overrides: object) -> SlashContext:
    values: dict[str, object] = {
        "workspace": tmp_path,
        "permission": PermissionMode.READ_ONLY,
        "mode": WorkMode.ASK,
        "trusted": False,
        "settings": SimpleNamespace(state_dir=tmp_path / "state"),
        "pending_run_id": None,
        "last_result": None,
        "last_run_id": None,
        "busy": False,
        "model_label": "deepseek/deepseek-chat",
    }
    values.update(overrides)
    return SlashContext(**values)  # type: ignore[arg-type]


def test_help_lists_every_builtin_command() -> None:
    for name in BUILTIN_COMMANDS:
        assert f"/{name}" in HELP


def test_unknown_slash_is_error_and_never_a_prompt(tmp_path: Path) -> None:
    result = dispatch_slash("/foo", _ctx(tmp_path))
    assert result.kind == "error"
    assert "/help" in result.message
    assert result.prompt is None


def test_non_slash_input_is_error_not_prompt(tmp_path: Path) -> None:
    result = dispatch_slash("implement the feature", _ctx(tmp_path))
    assert result.kind == "error"
    assert "/help" in result.message
    assert result.prompt is None


def test_leading_space_is_not_a_command(tmp_path: Path) -> None:
    result = dispatch_slash(" /help", _ctx(tmp_path))
    assert result.kind == "error"
    assert result.prompt is None


def test_fork_kind_includes_run_id(tmp_path: Path) -> None:
    result = dispatch_slash("/fork abc123 extra prompt", _ctx(tmp_path))
    assert result.kind == "fork"
    assert result.run_id == "abc123"
    assert result.prompt == "extra prompt"


def test_fork_requires_run_id(tmp_path: Path) -> None:
    result = dispatch_slash("/fork", _ctx(tmp_path))
    assert result.kind == "error"
    assert "Usage: /fork RUN_ID" in result.message


def test_resume_kind_includes_run_id(tmp_path: Path) -> None:
    result = dispatch_slash("/resume run-9", _ctx(tmp_path))
    assert result.kind == "resume"
    assert result.run_id == "run-9"
    assert result.approved is True


def test_mode_plan_changes_mode_not_permission(tmp_path: Path) -> None:
    result = dispatch_slash("/mode plan", _ctx(tmp_path))
    assert result.kind == "mode"
    assert result.mode is WorkMode.PLAN
    assert result.permission is None


def test_mode_rejects_permission_values(tmp_path: Path) -> None:
    result = dispatch_slash("/mode full", _ctx(tmp_path))
    assert result.kind == "error"
    assert "ask, plan, code, or review" in result.message


def test_permissions_full_untrusted_is_error(tmp_path: Path) -> None:
    result = dispatch_slash("/permissions full", _ctx(tmp_path, trusted=False))
    assert result.kind == "error"
    assert "--trust-workspace" in result.message
    assert result.permission is None


def test_permissions_full_trusted_updates(tmp_path: Path) -> None:
    result = dispatch_slash("/permissions full", _ctx(tmp_path, trusted=True))
    assert result.kind == "permission"
    assert result.permission is PermissionMode.FULL


def test_steer_kind_carries_text(tmp_path: Path) -> None:
    result = dispatch_slash("/steer focus on tests", _ctx(tmp_path))
    assert result.kind == "steer"
    assert result.prompt == "focus on tests"


def test_review_starts_read_only_prompt(tmp_path: Path) -> None:
    result = dispatch_slash("/review", _ctx(tmp_path))
    assert result.kind == "start_run"
    assert result.prompt == REVIEW_PROMPT
    assert "Do not edit" in result.prompt


def test_approve_and_deny_require_pending_run(tmp_path: Path) -> None:
    missing = dispatch_slash("/approve", _ctx(tmp_path))
    assert missing.kind == "error"
    approved = dispatch_slash("/approve", _ctx(tmp_path, pending_run_id="wait-1"))
    assert approved.kind == "approve"
    assert approved.run_id == "wait-1"
    assert approved.approved is True
    denied = dispatch_slash("/deny", _ctx(tmp_path, pending_run_id="wait-1"))
    assert denied.kind == "deny"
    assert denied.approved is False


def test_cancel_kind(tmp_path: Path) -> None:
    assert dispatch_slash("/cancel", _ctx(tmp_path)).kind == "cancel"


def test_status_diff_test_and_model(tmp_path: Path) -> None:
    result = RunResult(
        run_id="r1",
        status=RunStatus.SUCCEEDED,
        summary="done",
        task_type=TaskType.REVIEW,
        diff="diff --git a/x",
        verification=VerificationResult(outcome=VerificationOutcome.SKIPPED),
    )
    ctx = _ctx(tmp_path, last_result=result, last_run_id="r1")
    status = dispatch_slash("/status", ctx)
    assert status.kind == "status"
    assert "r1" in status.message
    assert "succeeded" in status.message
    assert "diff --git" in dispatch_slash("/diff", ctx).message
    assert "skipped" in dispatch_slash("/test", ctx).message
    assert "deepseek/deepseek-chat" in dispatch_slash("/model", ctx).message


def test_mcp_lists_configured_server_names(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    McpConfigStore(state_dir).add(
        "docs",
        McpServer(transport="http", url="https://mcp.test/rpc"),
    )
    ctx = _ctx(tmp_path, settings=SimpleNamespace(state_dir=state_dir))
    result = dispatch_slash("/mcp", ctx)
    assert result.kind == "info"
    assert "docs" in result.message


def test_skills_uses_trusted_workspace_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def fake_roots(workspace: Path, *, extra=None, trusted_workspace: bool = False):
        seen["workspace"] = workspace
        seen["trusted"] = trusted_workspace
        return []

    monkeypatch.setattr("zhixiao_agent.slash.default_skill_roots", fake_roots)
    result = dispatch_slash("/skills", _ctx(tmp_path, trusted=True))
    assert result.kind == "info"
    assert seen["workspace"] == tmp_path
    assert seen["trusted"] is True


def test_trusted_custom_command_expands_and_applies_mode(tmp_path: Path) -> None:
    commands = tmp_path / ".zhixiao" / "commands"
    commands.mkdir(parents=True)
    (commands / "fix.md").write_text(
        "---\nname: fix\nmode: code\n---\nFix {{args}} safely.",
        encoding="utf-8",
    )
    result = dispatch_slash("/fix the parser", _ctx(tmp_path, trusted=True))
    assert result.kind == "start_run"
    assert result.prompt == "Fix the parser safely."
    assert result.mode is WorkMode.CODE


def test_untrusted_custom_command_is_unknown(tmp_path: Path) -> None:
    commands = tmp_path / ".zhixiao" / "commands"
    commands.mkdir(parents=True)
    (commands / "fix.md").write_text(
        "---\nname: fix\nmode: code\n---\nFix {{args}} safely.",
        encoding="utf-8",
    )
    result = dispatch_slash("/fix the parser", _ctx(tmp_path, trusted=False))
    assert result.kind == "error"
    assert result.prompt is None


def test_builtin_names_win_over_custom_commands(tmp_path: Path) -> None:
    commands = tmp_path / ".zhixiao" / "commands"
    commands.mkdir(parents=True)
    (commands / "help.md").write_text(
        "---\nname: help\nmode: ask\n---\nCustom {{args}}",
        encoding="utf-8",
    )
    result = dispatch_slash("/help", _ctx(tmp_path, trusted=True))
    assert result.kind == "help"
    assert result.prompt is None
    assert "/fork" in result.message


def test_workspace_without_argument_reports_current(tmp_path: Path) -> None:
    result = dispatch_slash("/workspace", _ctx(tmp_path))
    assert result.kind == "workspace"
    assert result.workspace is None
    assert str(tmp_path) in result.message
