from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx
import redis.asyncio as redis

from zhixiao_agent.model import ModelProfile, OpenAICompatibleModel
from zhixiao_agent.runtime import AgentRuntime, RuntimeConfig
from zhixiao_agent.types import PermissionMode

QUEUE = "run:queue"
EVENT_PREFIX = "run:events:"
RESULT_PREFIX = "run:result:"
GROUP = "zhixiao-workers"


def build_runtime() -> AgentRuntime:
    api_key = os.environ.get("LLM_API_KEY", "")
    if not api_key:
        raise RuntimeError("LLM_API_KEY is required by the worker")
    model = OpenAICompatibleModel(
        ModelProfile(
            provider=os.environ.get("LLM_PROVIDER", "deepseek"),
            model=os.environ.get("LLM_MODEL", "deepseek-chat"),
            api_base=os.environ.get("LLM_API_BASE", "https://api.deepseek.com/v1"),
            api_key=api_key,
        )
    )
    return AgentRuntime(model)


async def ensure_group(client: redis.Redis) -> None:
    try:
        await client.xgroup_create(QUEUE, GROUP, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def _run_git(*args: str) -> None:
    process = await asyncio.create_subprocess_exec(
        "git", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode:
        detail = (stderr or stdout).decode(errors="replace").strip()
        raise RuntimeError(f"git workspace preparation failed: {detail}")


async def prepare_workspace(job: dict[str, str]) -> Path:
    explicit = job.get("workspace", "").strip()
    if explicit:
        return Path(explicit).resolve(strict=True)

    base = Path(os.environ.get("WORKSPACE_BASE", "/workspace/runs")).resolve()
    target = base / f"run-{job['run_id']}"
    source_text = job.get("repository_root", "").strip()
    if source_text:
        source = Path(source_text).resolve(strict=True)
        if not (source / ".git").exists():
            return source
        if target.exists():
            return target.resolve(strict=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        branch = f"agent/run-{job['run_id']}"
        await _run_git(
            "-C",
            str(source),
            "worktree",
            "add",
            "-b",
            branch,
            str(target),
            job.get("default_branch") or "main",
        )
        return target.resolve(strict=True)

    clone_url = job.get("clone_url", "").strip()
    if not clone_url:
        raise RuntimeError("job has neither workspace, repository_root nor clone_url")
    if job.get("network_approved", "false").lower() != "true":
        raise PermissionError("network clone requires an approved network operation")
    if target.exists():
        return target.resolve(strict=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    await _run_git(
        "clone",
        "--single-branch",
        "--branch",
        job.get("default_branch") or "main",
        clone_url,
        str(target),
    )
    return target.resolve(strict=True)


def normalize_event(event: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    name = str(event.get("event", "output"))
    data = dict(event.get("data") or {})
    data["source_event"] = name
    data["source_sequence"] = event.get("sequence")
    if name in {"run_started", "run_finished"}:
        normalized = "task_end" if name == "run_finished" else "run"
    elif name == "plan_created":
        normalized = "step"
    elif name == "approval_required":
        normalized = "approval"
    elif name == "tool_result":
        normalized = "tool"
    elif name == "verification_finished":
        normalized = "terminal"
        data["line"] = (
            f"{data.get('command', 'verification')} exited with "
            f"{data.get('exit_code', 'unknown')} ({data.get('status', 'unknown')})"
        )
    else:
        normalized = "output"
        data.setdefault("content", name)
    projected = [(normalized, data)]
    if name == "tool_result":
        projected.append(
            (
                "terminal",
                {
                    "line": f"{data.get('tool', 'tool')}: {data.get('summary', '')}",
                    "source_event": name,
                },
            )
        )
    return projected


async def publish_result(client: redis.Redis, run_id: str, payload: dict[str, Any]) -> None:
    stream = f"{EVENT_PREFIX}{run_id}"
    for event in payload.get("events", []):
        for event_name, event_data in normalize_event(event):
            await client.xadd(
                stream,
                {
                    "event": event_name,
                    "data": json.dumps(event_data, ensure_ascii=False),
                },
                maxlen=10_000,
                approximate=True,
            )
    await client.xadd(
        stream,
        {
            "event": "task_end",
            "data": json.dumps(
                {
                    "status": payload.get("status", "failed"),
                    "summary": payload.get("summary", ""),
                },
                ensure_ascii=False,
            ),
        },
        maxlen=10_000,
        approximate=True,
    )
    await client.hset(
        f"{RESULT_PREFIX}{run_id}",
        mapping={"payload": json.dumps(payload, ensure_ascii=False)},
    )


async def post_result(run_id: str, payload: dict[str, Any]) -> None:
    base_url = os.environ.get("API_BASE_URL", "http://api:8000/api/v1").rstrip("/")
    token = os.environ.get("WORKER_CALLBACK_TOKEN", "")
    if not token:
        raise RuntimeError("WORKER_CALLBACK_TOKEN is required by the worker")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{base_url}/internal/task-runs/{run_id}/result",
            headers={"X-Worker-Token": token},
            json=payload,
        )
        response.raise_for_status()


async def process_job(client: redis.Redis, runtime: AgentRuntime, job: dict[str, str]) -> None:
    run_id = job["run_id"]
    cached = await client.hget(f"{RESULT_PREFIX}{run_id}", "payload")
    if cached:
        await post_result(run_id, json.loads(cached))
        return
    try:
        workspace = await prepare_workspace(job)
        await client.xadd(
            f"{EVENT_PREFIX}{run_id}",
            {"event": "run", "data": json.dumps({"status": "running"})},
        )
        result = await runtime.run(
            job["prompt"],
            workspace,
            RuntimeConfig(
                permission=PermissionMode(job.get("permission_mode", "read_only")),
                runner_backend=os.environ.get("RUNNER_BACKEND", "local"),
                approved=job.get("approved", "false").lower() == "true",
                test_command=job.get("test_command") or None,
                # prepare_workspace already created the per-run worktree/clone.
                isolate_worktree=False,
                workflow_definition=(
                    json.loads(job["workflow_definition"])
                    if job.get("workflow_definition")
                    else None
                ),
                workflow_version=(
                    int(job["workflow_version"]) if job.get("workflow_version") else None
                ),
            ),
            run_id=run_id,
        )
        payload = result.model_dump(mode="json")
    except Exception as exc:
        payload = {
            "run_id": run_id,
            "status": "failed",
            "summary": "Worker execution failed.",
            "task_type": "explore",
            "plan": [],
            "artifacts": [],
            "test_command": job.get("test_command") or None,
            "test_exit_code": None,
            "diff": "",
            "events": [],
            "error": str(exc),
        }
    await publish_result(client, run_id, payload)
    await post_result(run_id, payload)


async def serve() -> None:
    client = redis.from_url(
        os.environ.get("REDIS_URL", "redis://redis:6379/0"), decode_responses=True
    )
    await ensure_group(client)
    runtime = build_runtime()
    consumer = os.environ.get("WORKER_NAME", f"worker-{os.getpid()}")
    while True:
        messages = await client.xreadgroup(
            GROUP,
            consumer,
            {QUEUE: ">"},
            count=1,
            block=5_000,
        )
        for _, entries in messages:
            for message_id, job in entries:
                try:
                    await process_job(client, runtime, job)
                except Exception:
                    # Leave the message pending so another delivery can retry the callback.
                    logging.exception("worker job %s failed before acknowledgement", message_id)
                    continue
                await client.xack(QUEUE, GROUP, message_id)


if __name__ == "__main__":
    asyncio.run(serve())
