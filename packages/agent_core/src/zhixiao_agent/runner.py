from __future__ import annotations

import asyncio
import os
import re
import shlex
import signal
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .security import CommandPolicy, WorkspaceBoundary
from .types import PermissionMode


class CommandResult(BaseModel):
    command: str
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


class Runner(ABC):
    @abstractmethod
    async def run(
        self,
        command: str,
        *,
        permission: PermissionMode,
        timeout: int = 120,
        approved: bool = False,
    ) -> CommandResult: ...


class LocalRunner(Runner):
    def __init__(self, workspace: Path, *, policy: CommandPolicy | None = None):
        self.boundary = WorkspaceBoundary(workspace)
        self.policy = policy or CommandPolicy()

    async def run(
        self,
        command: str,
        *,
        permission: PermissionMode,
        timeout: int = 120,
        approved: bool = False,
    ) -> CommandResult:
        self.policy.validate(command, permission, approved=approved)
        args = shlex.split(command, posix=os.name != "nt")
        if not args:
            raise ValueError("command cannot be empty")
        process_kwargs: dict[str, Any] = {}
        if os.name == "nt":
            process_kwargs["creationflags"] = 0x00000200  # CREATE_NEW_PROCESS_GROUP
        else:
            process_kwargs["start_new_session"] = True
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=self.boundary.root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **process_kwargs,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            return CommandResult(
                command=command,
                exit_code=process.returncode or 0,
                stdout=stdout.decode(errors="replace"),
                stderr=stderr.decode(errors="replace"),
            )
        except TimeoutError:
            await _terminate_process_tree(process)
            await process.communicate()
            return CommandResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr=f"command timed out after {timeout}s",
                timed_out=True,
            )
        except asyncio.CancelledError:
            await _terminate_process_tree(process)
            await process.communicate()
            raise


async def _terminate_process_tree(process: asyncio.subprocess.Process) -> None:
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
            os.killpg(process.pid, signal.SIGKILL)  # type: ignore[attr-defined]
        except ProcessLookupError:
            pass
    if process.returncode is None:
        process.kill()


class BubblewrapRunner(Runner):
    """Linux process sandbox exposing only runtime binaries and the selected workspace."""

    def __init__(self, workspace: Path, *, network_enabled: bool = False):
        self.boundary = WorkspaceBoundary(workspace)
        self.policy = CommandPolicy()
        self.network_enabled = network_enabled

    async def run(
        self,
        command: str,
        *,
        permission: PermissionMode,
        timeout: int = 120,
        approved: bool = False,
    ) -> CommandResult:
        if os.name == "nt":
            raise RuntimeError("bubblewrap runner is only available on Linux")
        self.policy.validate(command, permission, approved=approved)
        command_args = shlex.split(command)
        if not command_args:
            raise ValueError("command cannot be empty")
        mount_mode = "--ro-bind" if permission is PermissionMode.READ_ONLY else "--bind"
        args = [
            "bwrap",
            "--die-with-parent",
            "--new-session",
        ]
        if self.network_enabled:
            args.extend(
                [
                    "--unshare-user",
                    "--unshare-ipc",
                    "--unshare-pid",
                    "--unshare-uts",
                    "--unshare-cgroup",
                ]
            )
        else:
            args.append("--unshare-all")
        args.extend(
            [
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--tmpfs",
                "/tmp",  # noqa: S108 - isolated sandbox tmpfs, not host /tmp
                mount_mode,
                str(self.boundary.root),
                "/workspace",
                "--chdir",
                "/workspace",
                "--setenv",
                "HOME",
                "/tmp",  # noqa: S108 - isolated sandbox home
                "--setenv",
                "PATH",
                "/usr/local/bin:/usr/bin:/bin",
            ]
        )
        for path in ("/usr", "/usr/local", "/bin", "/lib", "/lib64", "/etc/ssl"):
            if Path(path).exists():
                args.extend(["--ro-bind", path, path])
        args.extend(["--", *command_args])
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={"PATH": os.environ.get("PATH", ""), "LANG": os.environ.get("LANG", "C.UTF-8")},
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            return CommandResult(
                command=command,
                exit_code=process.returncode or 0,
                stdout=stdout.decode(errors="replace"),
                stderr=stderr.decode(errors="replace"),
            )
        except TimeoutError:
            process.kill()
            await process.communicate()
            return CommandResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr=f"command timed out after {timeout}s",
                timed_out=True,
            )
        except asyncio.CancelledError:
            process.kill()
            await process.communicate()
            raise


class DockerRunner(Runner):
    def __init__(
        self,
        workspace: Path,
        *,
        image: str = "python:3.11-slim",
        network: str = "none",
        memory: str = "2g",
        cpus: str = "2",
        storage: str | None = "2g",
    ):
        self.boundary = WorkspaceBoundary(workspace)
        self.image = image
        self.network = network
        self.memory = memory
        self.cpus = cpus
        self.storage = storage
        self.policy = CommandPolicy()

    async def run(
        self,
        command: str,
        *,
        permission: PermissionMode,
        timeout: int = 120,
        approved: bool = False,
    ) -> CommandResult:
        self.policy.validate(command, permission, approved=approved)
        if not re.fullmatch(r"[A-Za-z0-9._/@:-]+", self.image):
            raise ValueError("docker image contains unsupported characters")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", self.network):
            raise ValueError("docker network contains unsupported characters")
        command_args = shlex.split(command, posix=os.name != "nt")
        if not command_args:
            raise ValueError("command cannot be empty")
        # EDIT/EXECUTE/FULL need a writable workspace mount; READ_ONLY stays read-only.
        mount_mode = "ro" if permission is PermissionMode.READ_ONLY else "rw"
        mount_spec = f"type=bind,src={self.boundary.root},dst=/workspace"
        if mount_mode == "ro":
            mount_spec += ",readonly"
        args = [
            "docker",
            "run",
            "--rm",
            "--network",
            self.network,
            "--memory",
            self.memory,
            "--cpus",
            self.cpus,
            "--pids-limit",
            "256",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=256m",  # noqa: S108 - container-local tmpfs
            "--mount",
            mount_spec,
            "--workdir",
            "/workspace",
        ]
        if self.storage:
            args.extend(["--storage-opt", f"size={self.storage}"])
        args.extend([self.image, *command_args])
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            return CommandResult(
                command=command,
                exit_code=process.returncode or 0,
                stdout=stdout.decode(errors="replace"),
                stderr=stderr.decode(errors="replace"),
            )
        except TimeoutError:
            process.kill()
            await process.communicate()
            return CommandResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr=f"command timed out after {timeout}s",
                timed_out=True,
            )
        except asyncio.CancelledError:
            process.kill()
            await process.communicate()
            raise
