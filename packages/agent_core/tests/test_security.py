from pathlib import Path

import pytest

from zhixiao_agent.security import (
    CommandPolicy,
    PermissionDenied,
    WorkspaceBoundary,
    WorkspaceViolation,
)
from zhixiao_agent.types import PermissionMode


def test_workspace_boundary_rejects_parent_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    boundary = WorkspaceBoundary(workspace)

    with pytest.raises(WorkspaceViolation):
        boundary.resolve("../outside.txt")


def test_command_policy_requires_execute_permission() -> None:
    with pytest.raises(PermissionDenied):
        CommandPolicy().validate("python -m pytest", PermissionMode.EDIT)


def test_command_policy_blocks_shell_chaining() -> None:
    with pytest.raises(PermissionDenied):
        CommandPolicy().validate("pytest && git status", PermissionMode.EXECUTE)


def test_git_push_requires_approval() -> None:
    policy = CommandPolicy()
    with pytest.raises(PermissionDenied):
        policy.validate("git push origin main", PermissionMode.FULL)
    policy.validate("git push origin main", PermissionMode.FULL, approved=True)


def test_workspace_boundary_rejects_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    link = workspace / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation requires elevated privileges on this host")
    boundary = WorkspaceBoundary(workspace)
    with pytest.raises(WorkspaceViolation):
        boundary.resolve("link.txt", must_exist=True)


def test_docker_runner_mount_mode_by_permission() -> None:
    from zhixiao_agent.types import PermissionMode as PM

    for permission, expected in (
        (PM.READ_ONLY, "ro"),
        (PM.EDIT, "rw"),
        (PM.EXECUTE, "rw"),
        (PM.FULL, "rw"),
    ):
        mount_mode = "ro" if permission is PM.READ_ONLY else "rw"
        assert mount_mode == expected


@pytest.mark.asyncio
async def test_docker_runner_rejects_unsafe_image_before_spawn(tmp_path: Path) -> None:
    from zhixiao_agent.runner import DockerRunner

    runner = DockerRunner(tmp_path, image="python:latest;touch-pwned")
    with pytest.raises(ValueError, match="image"):
        await runner.run("python -V", permission=PermissionMode.EXECUTE)
