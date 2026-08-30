from __future__ import annotations

import asyncio
import os
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
            args = (
                ["diff", "--cached", "--binary"]
                if request.staged
                else ["diff", "--binary", "HEAD"]
            )
            exit_code, stdout, stderr = await _run_git(repo, *args)
            if exit_code != 0:
                return ToolResult.error("git diff failed", root_cause=stderr)
            patches = [stdout]
            if not request.staged:
                _, untracked, _ = await _run_git(
                    repo, "ls-files", "--others", "--exclude-standard", "-z"
                )
                for relative in filter(None, untracked.split("\0")):
                    normalized = relative.replace("\\", "/")
                    if normalized.startswith(".zhixiao/artifacts/"):
                        continue
                    code, patch, patch_error = await _run_git(
                        repo,
                        "diff",
                        "--no-index",
                        "--binary",
                        "--",
                        os.devnull,
                        relative,
                    )
                    if code not in {0, 1}:
                        return ToolResult.error("git diff failed", root_cause=patch_error)
                    patches.append(patch)
            full_diff = "".join(patches)
            diff = full_diff[: request.max_chars]
            return ToolResult.ok(
                f"collected {len(diff)} diff characters",
                diff,
                artifacts=[
                    Artifact(
                        kind="git_diff",
                        path=str(repo),
                        description="working tree diff",
                        truncated=len(full_diff) > request.max_chars,
                    )
                ],
            )
        except (OSError, ValueError, PermissionDenied) as exc:
            return ToolResult.error("git diff failed", root_cause=str(exc))


async def _run_git(repository: Path, *arguments: str) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        "git",
        *arguments,
        cwd=repository,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return (
        process.returncode or 0,
        stdout.decode(errors="replace"),
        stderr.decode(errors="replace"),
    )


async def _git_text(repository: Path, *arguments: str) -> str:
    code, stdout, stderr = await _run_git(repository, *arguments)
    if code != 0:
        raise RuntimeError(stderr or f"git {' '.join(arguments)} failed")
    return stdout.strip()


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
        runner = LocalRunner(repository)
        branch = self.branch_name(run_id)
        status = await runner.run("git status --porcelain", permission=PermissionMode.EXECUTE)
        if status.exit_code != 0:
            raise RuntimeError(status.stderr or "unable to inspect repository status")
        dirty_paths = [line[3:] for line in status.stdout.splitlines() if len(line) > 3]
        if dirty_paths:
            joined = ", ".join(dirty_paths[:20])
            if len(dirty_paths) > 20:
                joined += f", ... ({len(dirty_paths) - 20} more)"
            raise RuntimeError(f"source repository has uncommitted changes: {joined}")

        if resolved_target.is_dir():
            probe = await LocalRunner(resolved_target).run(
                "git rev-parse --show-toplevel", permission=PermissionMode.EXECUTE
            )
            if probe.exit_code == 0 and Path(probe.stdout.strip()).resolve() == resolved_target:
                branch_probe = await LocalRunner(resolved_target).run(
                    "git branch --show-current", permission=PermissionMode.EXECUTE
                )
                if branch_probe.stdout.strip() == branch:
                    return resolved_target
            raise RuntimeError(f"worktree target already exists: {resolved_target}")

        resolved_target.parent.mkdir(parents=True, exist_ok=True)
        result = await runner.run(
            "git worktree add -b "
            f"{branch} {resolved_target}",
            permission=PermissionMode.EXECUTE,
        )
        if result.exit_code != 0 and "already exists" in result.stderr:
            result = await runner.run(
                f"git worktree add {resolved_target} {branch}",
                permission=PermissionMode.EXECUTE,
            )
        if result.exit_code != 0:
            raise RuntimeError(result.stderr or "unable to create worktree")
        return resolved_target

    async def manifest(self, run_id: str, target: Path) -> dict[str, str]:
        repository = self.boundary.root
        resolved_target = target.resolve(strict=True)
        if repository in resolved_target.parents or resolved_target == repository:
            raise ValueError("worktree target must be outside the source repository")
        return {
            "repository": str(repository),
            "base_sha": await _git_text(repository, "rev-parse", "HEAD"),
            "branch": self.branch_name(run_id),
            "path": str(resolved_target),
        }

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
