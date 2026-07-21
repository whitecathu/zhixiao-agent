from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..runner import LocalRunner
from ..security import PermissionDenied, WorkspaceBoundary
from ..types import Artifact, PermissionMode, ToolResult
from .base import BaseTool, ToolContext


class GitPathInput(BaseModel):
    path: str = "."


class GitStatusTool(BaseTool):
    name = "git_status"
    description = "Show the concise Git status for the workspace."
    input_model = GitPathInput

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        path = self.validate(arguments).path
        try:
            repo = context.boundary.resolve(path, must_exist=True)
            runner = LocalRunner(repo)
            result = await runner.run("git status --short", permission=PermissionMode.EXECUTE)
            if result.exit_code != 0:
                return ToolResult.error("git status failed", root_cause=result.stderr)
            return ToolResult.ok("Git status collected", result.stdout)
        except (OSError, ValueError, PermissionDenied) as exc:
            return ToolResult.error("git status failed", root_cause=str(exc))


class GitDiffInput(GitPathInput):
    staged: bool = False
    max_chars: int = Field(default=200_000, ge=1, le=2_000_000)


class GitDiffTool(BaseTool):
    name = "git_diff"
    description = "Return the current Git patch without modifying repository state."
    input_model = GitDiffInput

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        request = self.validate(arguments)
        try:
            repo = context.boundary.resolve(request.path, must_exist=True)
            runner = LocalRunner(repo)
            command = "git diff --cached" if request.staged else "git diff"
            result = await runner.run(command, permission=PermissionMode.EXECUTE)
            if result.exit_code != 0:
                return ToolResult.error("git diff failed", root_cause=result.stderr)
            diff = result.stdout[: request.max_chars]
            return ToolResult.ok(
                f"collected {len(diff)} diff characters",
                diff,
                artifacts=[
                    Artifact(kind="git_diff", path=str(repo), description="working tree diff")
                ],
            )
        except (OSError, ValueError, PermissionDenied) as exc:
            return ToolResult.error("git diff failed", root_cause=str(exc))


class WorktreeManager:
    """Create isolated worktrees with validated, deterministic branch names."""

    def __init__(self, repository: Path):
        self.boundary = WorkspaceBoundary(repository)

    @staticmethod
    def branch_name(run_id: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9._-]", "-", run_id).strip("-.")
        if not safe:
            raise ValueError("run_id does not contain a valid branch component")
        return f"zhixiao/{safe[:64]}"

    async def create(self, run_id: str, target: Path) -> Path:
        repository = self.boundary.root
        resolved_target = target.resolve()
        if repository in resolved_target.parents or resolved_target == repository:
            raise ValueError("worktree target must be outside the source repository")
        resolved_target.parent.mkdir(parents=True, exist_ok=True)
        runner = LocalRunner(repository)
        branch = self.branch_name(run_id)
        result = await runner.run(
            f"git worktree add -b {branch} {resolved_target}",
            permission=PermissionMode.EXECUTE,
        )
        if result.exit_code != 0:
            raise RuntimeError(result.stderr or "unable to create worktree")
        return resolved_target

    async def remove(self, target: Path, *, approved: bool = False) -> None:
        if not approved:
            raise PermissionDenied("worktree removal requires explicit approval")
        runner = LocalRunner(self.boundary.root)
        result = await runner.run(
            f"git worktree remove {target.resolve()}",
            permission=PermissionMode.FULL,
            approved=True,
        )
        if result.exit_code != 0:
            raise RuntimeError(result.stderr or "unable to remove worktree")
