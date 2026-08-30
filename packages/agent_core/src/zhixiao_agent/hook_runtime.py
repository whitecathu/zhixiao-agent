from __future__ import annotations

import asyncio
import os
import shlex
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .security import CommandPolicy, WorkspaceBoundary
from .tools.registry import ToolRegistry
from .types import PermissionMode, ToolResult

_SAFE_ENV = {
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "PYTHONIOENCODING",
    "VIRTUAL_ENV",
}


@dataclass(frozen=True)
class HookExecution:
    name: str
    command: str
    status: str
    exit_code: int | None = None
    summary: str = ""
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


class HookFailure(RuntimeError):
    def __init__(self, execution: HookExecution):
        super().__init__(execution.summary)
        self.execution = execution


async def run_hooks(
    name: str,
    commands: list[str],
    *,
    workspace: Path,
    trusted: bool,
    permission: PermissionMode,
    timeout: int,
) -> list[HookExecution]:
    if not commands:
        return []
    if not trusted:
        execution = HookExecution(
            name=name,
            command="",
            status="blocked",
            summary="workspace hooks require a trusted workspace",
        )
        raise HookFailure(execution)
    if permission not in {PermissionMode.EXECUTE, PermissionMode.FULL}:
        execution = HookExecution(
            name=name,
            command="",
            status="blocked",
            summary="hooks require execute or full permission",
        )
        raise HookFailure(execution)
    results: list[HookExecution] = []
    for command in commands:
        execution = await _run_hook(
            name,
            command,
            workspace=workspace,
            permission=permission,
            timeout=timeout,
        )
        results.append(execution)
        if execution.status != "succeeded":
            raise HookFailure(execution)
    return results


async def _run_hook(
    name: str,
    command: str,
    *,
    workspace: Path,
    permission: PermissionMode,
    timeout: int,
) -> HookExecution:
    boundary = WorkspaceBoundary(workspace)
    try:
        CommandPolicy().validate(command, permission, approved=False)
    except (PermissionError, ValueError) as exc:
        return HookExecution(
            name=name,
            command=command,
            status="blocked",
            summary=f"hook was blocked: {exc}",
            stderr=str(exc),
        )
    args = shlex.split(command, posix=os.name != "nt")
    if not args:
        return HookExecution(
            name=name,
            command=command,
            status="blocked",
            summary="hook command cannot be empty",
        )
    sanitized = {
        key: value for key, value in os.environ.items() if key.upper() in _SAFE_ENV
    }
    sanitized["ZHIXIAO_HOOK"] = name
    sanitized["ZHIXIAO_WORKSPACE"] = str(boundary.root)
    process_kwargs: dict[str, Any] = {}
    if os.name == "nt":
        process_kwargs["creationflags"] = 0x00000200
    else:
        process_kwargs["start_new_session"] = True
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=boundary.root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=sanitized,
            **process_kwargs,
        )
    except OSError as exc:
        return HookExecution(
            name=name,
            command=command,
            status="blocked",
            summary=f"hook was blocked: {exc}",
            stderr=str(exc),
        )
    timed_out = False
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        timed_out = True
        await _terminate(process)
        stdout, stderr = await process.communicate()
    exit_code = process.returncode if process.returncode is not None else -1
    status = "succeeded" if exit_code == 0 and not timed_out else "failed"
    return HookExecution(
        name=name,
        command=command,
        status=status,
        exit_code=exit_code,
        summary=(
            f"hook {name} completed"
            if status == "succeeded"
            else (
                f"hook {name} timed out after {timeout}s"
                if timed_out
                else f"hook {name} failed with exit code {exit_code}"
            )
        ),
        stdout=stdout.decode(errors="replace")[-8_000:],
        stderr=stderr.decode(errors="replace")[-8_000:],
        timed_out=timed_out,
    )


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if os.name == "nt":
        terminator = await asyncio.create_subprocess_exec(
            "taskkill",
            "/PID",
            str(process.pid),
            "/T",
            "/F",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await terminator.wait()
    else:
        try:
            kill_process_group = getattr(os, "killpg", None)
            if callable(kill_process_group):
                kill_process_group(process.pid, getattr(signal, "SIGKILL", 9))
            else:
                process.kill()
        except ProcessLookupError:
            pass
    if process.returncode is None:
        process.kill()


class HookedToolRegistry(ToolRegistry):
    """Wrap tool execution so trusted hooks are ordered around the real invocation."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        hooks: dict[str, list[str]],
        workspace: Path,
        trusted: bool,
        permission: PermissionMode,
        timeout: int,
    ):
        super().__init__()
        self._registry = registry
        self._hooks = hooks
        self._workspace = workspace
        self._trusted = trusted
        self._permission = permission
        self._timeout = timeout

    def get(self, name: str) -> Any:
        return self._registry.get(name)

    def names(self) -> frozenset[str]:
        return self._registry.names()

    def schemas(self, allowed: set[str] | None = None) -> list[dict[str, Any]]:
        return self._registry.schemas(allowed)

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Any,
        *,
        allowed: set[str] | None = None,
    ) -> ToolResult:
        try:
            await run_hooks(
                "before_tool",
                self._hooks.get("before_tool", []),
                workspace=self._workspace,
                trusted=self._trusted,
                permission=self._permission,
                timeout=self._timeout,
            )
        except HookFailure as exc:
            return ToolResult.error(
                "before_tool hook failed",
                root_cause=exc.execution.summary,
                stop_condition="fix or disable the failing workspace hook",
            )
        result = await self._registry.execute(name, arguments, context, allowed=allowed)
        try:
            await run_hooks(
                "after_tool",
                self._hooks.get("after_tool", []),
                workspace=self._workspace,
                trusted=self._trusted,
                permission=self._permission,
                timeout=self._timeout,
            )
        except HookFailure as exc:
            return ToolResult.error(
                "after_tool hook failed",
                root_cause=exc.execution.summary,
                stop_condition="fix or disable the failing workspace hook",
            )
        return result


def quote_hook_argument(value: str) -> str:
    """Public helper for command authors; hooks themselves are not templated."""
    return shlex.quote(value)
