from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from zhixiao_agent.cli_state import RunManifest, SessionStore
from zhixiao_agent.session_controller import (
    SCHEMA_VERSION,
    ApprovalPolicy,
    WorkMode,
    control_path,
    execute_local,
    fork_local,
    interrupt_local,
    local_runtime_bundle,
    resume_local,
)
from zhixiao_agent.settings import load_settings
from zhixiao_agent.types import PermissionMode, RunBudget


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZHIXIAO_CONFIG_FILE", str(tmp_path / "user-config.toml"))
    monkeypatch.setenv("ZHIXIAO_STATE_DIR", str(tmp_path / "state"))
    return load_settings(tmp_path)


async def _noop(_event: dict) -> None:
    return None


@pytest.mark.asyncio
async def test_execute_local_writes_schema_version_1_1(
    tmp_path: Path, settings
) -> None:
    payload = await execute_local(
        "review this repository",
        workspace=tmp_path,
        settings=settings,
        permission=PermissionMode.READ_ONLY,
        mode=WorkMode.ASK,
        approval_policy=ApprovalPolicy.NEVER,
        approved=False,
        approve_ops=frozenset(),
        network=frozenset(),
        offline=True,
        runner="local",
        test_command=None,
        max_model_rounds=4,
        max_tool_calls=8,
        max_tokens=None,
        max_cost_usd=None,
        allow_unverified=None,
        trusted=False,
        on_event=_noop,
    )

    assert payload["schema_version"] == SCHEMA_VERSION
    manifest = SessionStore(settings.state_dir).get(payload["run_id"])
    assert manifest is not None
    assert manifest.schema_version == "1.1"
    assert payload["status"] == "succeeded"


def test_interrupt_local_writes_control_file_and_marks_interrupted(
    tmp_path: Path, settings
) -> None:
    store = SessionStore(settings.state_dir)
    created = store.save(
        RunManifest(
            run_id="run-interrupt",
            prompt="do work",
            workspace=str(tmp_path),
            status="running",
        )
    )
    assert created.is_file()

    payload = interrupt_local("run-interrupt", settings=settings)

    assert payload["schema_version"] == "1.1"
    assert payload["status"] == "interrupted"
    assert payload["run_id"] == "run-interrupt"
    assert "zhixiao resume run-interrupt" in payload["next_actions"]
    stop_file = control_path(settings.state_dir, "run-interrupt")
    assert stop_file.is_file()
    assert "interrupt" in stop_file.read_text(encoding="utf-8")
    updated = store.get("run-interrupt")
    assert updated is not None
    assert updated.status == "interrupted"

    with pytest.raises(ValueError, match="local run not found"):
        interrupt_local("missing-run", settings=settings)


def test_local_runtime_bundle_passes_mode(tmp_path: Path, settings) -> None:
    _runtime, config, hooks = local_runtime_bundle(
        settings=settings,
        workspace=tmp_path,
        permission=PermissionMode.READ_ONLY,
        mode=WorkMode.PLAN,
        approval_policy=ApprovalPolicy.NEVER,
        approved=False,
        approve_ops=frozenset(),
        network=frozenset(),
        offline=True,
        runner="local",
        test_command=None,
        budget=RunBudget(),
        allow_unverified=None,
        trusted=False,
        command_timeout=30,
        command_tools=("read_file", "apply_patch"),
    )

    assert hooks == {}
    assert config.tool_metadata is not None
    assert config.tool_metadata["mode"] == "plan"
    assert config.tool_metadata["command_tools"] == ["read_file", "apply_patch"]
    if hasattr(config, "mode"):
        assert config.mode == "plan"
    if hasattr(config, "state_dir"):
        assert config.state_dir == settings.state_dir


@pytest.mark.asyncio
async def test_execute_local_applies_custom_command_mode(
    tmp_path: Path, settings
) -> None:
    commands = tmp_path / ".zhixiao" / "commands"
    commands.mkdir(parents=True)
    (commands / "fix.md").write_text(
        "---\nname: fix\nmode: code\ntools: read_file,apply_patch\n---\nFix {{args}} safely.",
        encoding="utf-8",
    )

    payload = await execute_local(
        "/fix the parser",
        workspace=tmp_path,
        settings=settings,
        permission=PermissionMode.READ_ONLY,
        mode=WorkMode.ASK,
        approval_policy=ApprovalPolicy.NEVER,
        approved=False,
        approve_ops=frozenset(),
        network=frozenset(),
        offline=True,
        runner="local",
        test_command=None,
        max_model_rounds=4,
        max_tool_calls=8,
        max_tokens=None,
        max_cost_usd=None,
        allow_unverified=None,
        trusted=True,
        on_event=_noop,
    )

    manifest = SessionStore(settings.state_dir).get(payload["run_id"])
    assert manifest is not None
    assert manifest.mode == "code"
    assert manifest.prompt == "Fix the parser safely."


def _execute_kwargs(tmp_path: Path, settings: Any, **overrides: Any) -> dict[str, Any]:
    values = dict(
        workspace=tmp_path,
        settings=settings,
        permission=PermissionMode.READ_ONLY,
        mode=WorkMode.ASK,
        approval_policy=ApprovalPolicy.NEVER,
        approved=False,
        approve_ops=frozenset(),
        network=frozenset(),
        offline=True,
        runner="local",
        test_command=None,
        max_model_rounds=4,
        max_tool_calls=8,
        max_tokens=None,
        max_cost_usd=None,
        allow_unverified=None,
        trusted=False,
        on_event=_noop,
    )
    values.update(overrides)
    return values


@pytest.mark.asyncio
async def test_resume_local_after_approval(tmp_path: Path, settings) -> None:
    pending = await execute_local(
        "implement a feature",
        **_execute_kwargs(
            tmp_path,
            settings,
            permission=PermissionMode.EDIT,
            mode=WorkMode.CODE,
            approval_policy=ApprovalPolicy.ON_REQUEST,
            allow_unverified="offline resume fixture has no test suite",
        ),
    )

    assert pending["status"] == "awaiting_approval"
    run_id = pending["run_id"]

    completed = await resume_local(
        run_id,
        settings=settings,
        approved=True,
        offline=True,
        on_event=_noop,
    )

    assert completed["status"] == "succeeded"
    assert completed["run_id"] == run_id
    manifest = SessionStore(settings.state_dir).get(run_id)
    assert manifest is not None
    assert manifest.status == "succeeded"


@pytest.mark.asyncio
async def test_fork_local_creates_child_with_parent_run_id(
    tmp_path: Path, settings
) -> None:
    parent = await execute_local(
        "review this repository",
        **_execute_kwargs(tmp_path, settings),
    )
    assert parent["status"] == "succeeded"

    child = await fork_local(
        parent["run_id"],
        settings=settings,
        offline=True,
        on_event=_noop,
    )

    assert child["run_id"] != parent["run_id"]
    child_manifest = SessionStore(settings.state_dir).get(child["run_id"])
    assert child_manifest is not None
    assert child_manifest.parent_run_id == parent["run_id"]
    parent_manifest = SessionStore(settings.state_dir).get(parent["run_id"])
    assert parent_manifest is not None
    assert parent_manifest.parent_run_id is None
