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
