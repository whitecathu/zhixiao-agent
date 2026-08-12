"""Task-run queue shared by the API and worker processes."""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass
from typing import Protocol

from app.core.config import settings
from app.core.redis_client import RedisClient
from zhixiao_agent.job_security import (
    ISSUED_AT_FIELD,
    NONCE_FIELD,
    SIGNATURE_FIELD,
    sign_job_fields,
)

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
    # Plan/run-start approval only — does not unlock destructive, publish, or network tools.
    approved: str = "false"
    ops_approved: str = "false"
    ops_capabilities: str = "[]"
    clone_approved: str = "false"
    network_approved: str = "false"
    network_capabilities: str = "[]"
    workflow_definition: str = ""
    workflow_version: str = ""
    engine: str = "langgraph"
    roles_json: str = ""

    def fields(self) -> dict[str, str]:
        fields = {
            "run_id": self.run_id,
            "prompt": self.prompt,
            "permission_mode": self.permission_mode,
            "repository_root": self.repository_root,
            "clone_url": self.clone_url,
            "default_branch": self.default_branch,
            "workspace": self.workspace,
            "test_command": self.test_command,
            "approved": self.approved,
            "ops_approved": self.ops_approved,
            "ops_capabilities": self.ops_capabilities,
            "clone_approved": self.clone_approved,
            "network_approved": self.network_approved,
            "network_capabilities": self.network_capabilities,
            "workflow_definition": self.workflow_definition,
            "workflow_version": self.workflow_version,
            "engine": self.engine,
            "roles_json": self.roles_json,
            ISSUED_AT_FIELD: str(int(time.time())),
            NONCE_FIELD: secrets.token_hex(16),
        }
        secret = settings.WORKER_JOB_SIGNING_SECRET or settings.WORKER_CALLBACK_TOKEN
        fields[SIGNATURE_FIELD] = sign_job_fields(fields, secret)
        return fields


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
