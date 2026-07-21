"""Task-run queue shared by the API and worker processes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from app.core.config import settings
from app.core.redis_client import RedisClient

RUN_QUEUE_KEY = "run:queue"


@dataclass(frozen=True, slots=True)
class RunJob:
    run_id: str
    prompt: str
    permission_mode: str
    repository_root: str = ""
    clone_url: str = ""
    default_branch: str = "main"
    workspace: str = ""
    test_command: str = ""
    approved: str = "true"
    network_approved: str = "false"

    def fields(self) -> dict[str, str]:
        return {
            "run_id": self.run_id,
            "prompt": self.prompt,
            "permission_mode": self.permission_mode,
            "repository_root": self.repository_root,
            "clone_url": self.clone_url,
            "default_branch": self.default_branch,
            "workspace": self.workspace,
            "test_command": self.test_command,
            "approved": self.approved,
            "network_approved": self.network_approved,
        }


class JobStore(Protocol):
    async def enqueue(self, job: RunJob) -> str: ...


class MemoryJobStore:
    def __init__(self) -> None:
        self.jobs: list[RunJob] = []
        self._condition = asyncio.Condition()

    async def enqueue(self, job: RunJob) -> str:
        async with self._condition:
            self.jobs.append(job)
            self._condition.notify_all()
            return f"{len(self.jobs)}-0"


class RedisStreamJobStore:
    async def enqueue(self, job: RunJob) -> str:
        client = await RedisClient.get()
        return str(await client.xadd(RUN_QUEUE_KEY, job.fields(), maxlen=10_000, approximate=True))


class RunQueue:
    _default: RunQueue | None = None

    def __init__(self, store: JobStore) -> None:
        self.store = store

    @classmethod
    def memory(cls) -> RunQueue:
        return cls(MemoryJobStore())

    @classmethod
    def default(cls) -> RunQueue:
        if cls._default is None:
            store: JobStore = (
                MemoryJobStore() if settings.APP_ENV == "test" else RedisStreamJobStore()
            )
            cls._default = cls(store)
        return cls._default

    async def enqueue(self, job: RunJob) -> str:
        return await self.store.enqueue(job)
