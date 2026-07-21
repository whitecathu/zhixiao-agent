from __future__ import annotations

import asyncio
import os
import shlex
from abc import ABC, abstractmethod
from pathlib import Path

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
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=self.boundary.root,
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
        mount_mode = "rw" if permission is PermissionMode.FULL else "ro"
        docker_command = " ".join(
            [
                "docker run --rm",
                f"--network {self.network}",
                f"--memory {self.memory}",
                f"--cpus {self.cpus}",
                *([f"--storage-opt size={self.storage}"] if self.storage else []),
                "--pids-limit 256",
                "--read-only",
                "--tmpfs /tmp:rw,noexec,nosuid,size=256m",
                f'-v "{self.boundary.root}:/workspace:{mount_mode}"',
                "-w /workspace",
                self.image,
                command,
            ]
        )
        local = LocalRunner(self.boundary.root)
        return await local.run(
            docker_command,
            permission=permission,
            timeout=timeout,
            approved=approved,
        )
