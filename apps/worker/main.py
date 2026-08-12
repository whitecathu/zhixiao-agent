from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import redis.asyncio as redis

from zhixiao_agent.job_security import verify_job_fields
from zhixiao_agent.metagpt_runtime import run_metagpt_team
from zhixiao_agent.model import ModelProfile, OpenAICompatibleModel
from zhixiao_agent.runtime import AgentRuntime, RuntimeConfig
from zhixiao_agent.subagent import build_sub_agent_handler
from zhixiao_agent.tools.mcp_adapter import mcp_config_from_env
from zhixiao_agent.tools.registry import build_default_registry
from zhixiao_agent.types import PermissionMode

QUEUE = "run:queue"
EVENT_PREFIX = "run:events:"
RESULT_PREFIX = "run:result:"
CONTROL_PREFIX = "run:control:"
GROUP = "zhixiao-workers"
KNOWN_OPS_CAPABILITIES = frozenset(
    {"destructive_command", "git_publish", "mcp", "sub_agent"}
)
KNOWN_NETWORK_CAPABILITIES = frozenset({"web", "git_publish", "mcp"})
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SAFE_BRANCH = re.compile(r"^[A-Za-z0-9._/-]{1,255}$")
_SECRET_VALUE = re.compile(
    r"(?i)((?:authorization|api[_-]?key|password|secret|token)\s*[:=]\s*"
    r"(?:bearer\s+)?)[^\s,;]+"
)


def _safe_error(value: object) -> str:
    return _SECRET_VALUE.sub(r"\1[REDACTED]", str(value))[:4_000]


def _workspace_base() -> Path:
    return Path(os.environ.get("WORKSPACE_BASE", "/workspace/runs")).resolve()


def _allowed_source_roots() -> tuple[Path, ...]:
    configured = os.environ.get("WORKSPACE_SOURCE_ROOTS", "")
    roots = [item.strip() for item in configured.split(os.pathsep) if item.strip()]
    if not roots:
        roots = [str(_workspace_base())]
    return tuple(Path(item).resolve() for item in roots)


def _confined_path(value: str, roots: tuple[Path, ...], *, label: str) -> Path:
    candidate = Path(value).expanduser().resolve(strict=True)
    if not candidate.is_dir():
        raise ValueError(f"{label} must be an existing directory")
    for root in roots:
        try:
            candidate.relative_to(root)
            return candidate
        except ValueError:
            continue
    allowed = ", ".join(str(root) for root in roots)
    raise PermissionError(f"{label} escapes allowed roots: {allowed}")


def _runner_backend(permission: PermissionMode) -> str:
    backend = os.environ.get("RUNNER_BACKEND", "bubblewrap").strip().lower()
    if backend not in {"local", "docker", "bubblewrap"}:
        raise ValueError(f"unsupported RUNNER_BACKEND: {backend}")
    unsafe_local = os.environ.get("ALLOW_UNSANDBOXED_LOCAL_EXECUTION", "").lower() in {
        "1",
        "true",
        "yes",
    }
    if backend == "local" and permission in {PermissionMode.EXECUTE, PermissionMode.FULL}:
        if not unsafe_local:
            raise PermissionError(
                "execute/full runs require RUNNER_BACKEND=docker; "
                "set ALLOW_UNSANDBOXED_LOCAL_EXECUTION=true only for trusted local development"
            )
    return backend


def _job_signing_secret() -> str:
    return (
        os.environ.get("WORKER_JOB_SIGNING_SECRET")
        or os.environ.get("WORKER_CALLBACK_TOKEN")
        or ""
    )


def _verify_job(job: dict[str, str]) -> None:
    # Unit tests may exercise process_job directly; deployed workers always require signatures.
    if "PYTEST_CURRENT_TEST" in os.environ and not job.get("job_signature"):
        return
    secret = _job_signing_secret()
    max_age = int(os.environ.get("WORKER_JOB_MAX_AGE_SECONDS", "3600"))
    if not verify_job_fields(job, secret, max_age_seconds=max_age):
        raise PermissionError("worker job signature is missing, expired, or invalid")
    if job.get("engine", "langgraph") not in {"langgraph", "metagpt"}:
        raise PermissionError("worker job requested an unsupported engine")
    if not _SAFE_RUN_ID.fullmatch(job.get("run_id", "")):
        raise PermissionError("worker job contains an invalid run_id")


def _parse_ops_capabilities(job: dict[str, str]) -> frozenset[str]:
    try:
        raw = json.loads(job.get("ops_capabilities") or "[]")
    except json.JSONDecodeError as exc:
        raise PermissionError("ops_capabilities must be valid JSON") from exc
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise PermissionError("ops_capabilities must be a string list")
    capabilities = frozenset(raw)
    unknown = capabilities - KNOWN_OPS_CAPABILITIES
    if unknown:
        raise PermissionError(f"unknown ops capabilities: {', '.join(sorted(unknown))}")
    return capabilities


def _parse_network_capabilities(job: dict[str, str]) -> frozenset[str]:
    try:
        raw = json.loads(job.get("network_capabilities") or "[]")
    except json.JSONDecodeError as exc:
        raise PermissionError("network_capabilities must be valid JSON") from exc
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise PermissionError("network_capabilities must be a string list")
    capabilities = frozenset(raw)
    unknown = capabilities - KNOWN_NETWORK_CAPABILITIES
    if unknown:
        raise PermissionError(f"unknown network capabilities: {', '.join(sorted(unknown))}")
    return capabilities


def _validate_clone_url(value: str) -> str:
    parsed = urlsplit(value)
    allowed_schemes = {
        item.strip().lower()
        for item in os.environ.get("GIT_CLONE_ALLOWED_SCHEMES", "https").split(",")
        if item.strip()
    }
    if parsed.scheme.lower() not in allowed_schemes or not parsed.hostname:
        raise PermissionError("clone URL must use an explicitly allowed network scheme")
    if parsed.username or parsed.password:
        raise PermissionError("clone URL credentials must not be embedded in jobs")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost":
        raise PermissionError("clone URL cannot target localhost")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise PermissionError("clone URL cannot target a non-public IP address")
    allowed_hosts = {
        item.strip().rstrip(".").lower()
        for item in os.environ.get("GIT_CLONE_ALLOWED_HOSTS", "").split(",")
        if item.strip()
    }
    if allowed_hosts and host not in allowed_hosts:
        raise PermissionError("clone URL host is not allowlisted")
    if os.environ.get("APP_ENV") == "prod" and not allowed_hosts:
        raise RuntimeError("GIT_CLONE_ALLOWED_HOSTS is required in production")
    return value


def _validate_branch(value: str) -> str:
    if not _SAFE_BRANCH.fullmatch(value) or ".." in value or value.startswith(("-", "/")):
        raise PermissionError("default branch contains unsupported characters")
    return value


def _env_cost_per_million(name: str) -> float:
    """Parse optional USD-per-million token rates; unset/blank keeps ModelProfile default 0.0."""
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return 0.0
    return float(raw)


def build_model() -> OpenAICompatibleModel:
    api_key = os.environ.get("LLM_API_KEY", "")
    if not api_key:
        raise RuntimeError("LLM_API_KEY is required by the worker")
    return OpenAICompatibleModel(
        ModelProfile(
            provider=os.environ.get("LLM_PROVIDER", "deepseek"),
            model=os.environ.get("LLM_MODEL", "deepseek-chat"),
            api_base=os.environ.get("LLM_API_BASE", "https://api.deepseek.com/v1"),
            api_key=api_key,
            input_cost_per_million=_env_cost_per_million("LLM_INPUT_COST_PER_MILLION"),
            output_cost_per_million=_env_cost_per_million("LLM_OUTPUT_COST_PER_MILLION"),
        )
    )


def build_tool_metadata(
    *,
    model: OpenAICompatibleModel | None,
    workspace: Path,
    permission: PermissionMode,
    ops_approved: bool,
    ops_capabilities: frozenset[str],
    network_approved: bool,
    network_capabilities: frozenset[str],
    approved: bool,
    run_id: str,
    on_event: Any,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    mcp = mcp_config_from_env() if "mcp" in ops_capabilities else None
    if mcp:
        metadata.update(mcp)
        if (os.environ.get("MCP_HTTP_BASE") or "").strip():
            metadata["mcp_network_approved"] = "mcp" in network_capabilities
    if "git_publish" in ops_capabilities:
        metadata["publish_approved"] = True
        metadata["ops_capabilities"] = sorted(ops_capabilities)
    subagent_enabled = os.environ.get("SUBAGENT_ENABLED", "").lower() in {"1", "true", "yes"}
    if model is not None and subagent_enabled and "sub_agent" in ops_capabilities:
        metadata["sub_agent"] = build_sub_agent_handler(
            model,
            lambda: workspace,
            permission=PermissionMode.READ_ONLY,
            ops_approved=False,
            network_approved=False,
            approved=approved,
            parent_run_id=run_id,
            on_event=on_event,
        )
    return metadata


def build_runtime() -> AgentRuntime:
    model = build_model()
    experimental = bool(
        mcp_config_from_env()
        or os.environ.get("SUBAGENT_ENABLED", "").lower() in {"1", "true", "yes"}
        or os.environ.get("MCP_ENABLED", "").lower() in {"1", "true", "yes"}
        or os.environ.get("MCP_WHITELIST", "").strip()
        or os.environ.get("MCP_HTTP_BASE", "").strip()
    )
    registry = build_default_registry(include_experimental=experimental)
    return AgentRuntime(model, registry=registry)


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
        detail = _safe_error((stderr or stdout).decode(errors="replace").strip())
        raise RuntimeError(f"git workspace preparation failed: {detail}")


async def prepare_workspace(job: dict[str, str]) -> Path:
    base = _workspace_base()
    base.mkdir(parents=True, exist_ok=True)
    explicit = job.get("workspace", "").strip()
    if explicit:
        return _confined_path(explicit, (base,), label="workspace")

    target = base / f"run-{job['run_id']}"
    source_text = job.get("repository_root", "").strip()
    default_branch = _validate_branch(job.get("default_branch") or "main")
    if source_text:
        source = _confined_path(
            source_text,
            _allowed_source_roots(),
            label="repository_root",
        )
        if not (source / ".git").exists():
            raise ValueError("repository_root must be a Git repository")
        if target.exists():
            return _confined_path(str(target), (base,), label="prepared workspace")
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
            default_branch,
        )
        return target.resolve(strict=True)

    clone_url = job.get("clone_url", "").strip()
    if not clone_url:
        raise RuntimeError("job has neither workspace, repository_root nor clone_url")
    if job.get("clone_approved", "false").lower() != "true":
        raise PermissionError("network clone requires explicit clone approval")
    clone_url = _validate_clone_url(clone_url)
    if target.exists():
        return _confined_path(str(target), (base,), label="prepared workspace")
    target.parent.mkdir(parents=True, exist_ok=True)
    await _run_git(
        "clone",
        "--single-branch",
        "--branch",
        default_branch,
        "--",
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
    elif name == "model_turn":
        normalized = "output"
        data.setdefault("content", data.get("content") or "")
        data.setdefault("subtask_id", "main")
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


async def publish_event(client: redis.Redis, run_id: str, event: dict[str, Any]) -> None:
    stream = f"{EVENT_PREFIX}{run_id}"
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


async def publish_result(
    client: redis.Redis,
    run_id: str,
    payload: dict[str, Any],
    *,
    terminal_already_published: bool = False,
) -> None:
    stream = f"{EVENT_PREFIX}{run_id}"
    contains_run_finished = False
    for event in payload.get("events", []):
        contains_run_finished = contains_run_finished or event.get("event") == "run_finished"
        await publish_event(client, run_id, event)
    if not terminal_already_published and not contains_run_finished:
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


async def _should_stop(client: redis.Redis, run_id: str) -> bool:
    value = await client.get(f"{CONTROL_PREFIX}{run_id}")
    return value == "stop"


async def process_job(client: redis.Redis, runtime: AgentRuntime, job: dict[str, str]) -> None:
    _verify_job(job)
    run_id = job["run_id"]
    cached = await client.hget(f"{RESULT_PREFIX}{run_id}", "payload")
    if cached:
        await post_result(run_id, json.loads(cached))
        return
    live_sequences: set[int] = set()
    live_event_names: set[str] = set()

    async def on_event(event: dict[str, Any]) -> None:
        sequence = int(event.get("sequence") or 0)
        if sequence > 0 and sequence in live_sequences:
            return
        if sequence > 0:
            live_sequences.add(sequence)
        live_event_names.add(str(event.get("event", "")))
        await publish_event(client, run_id, event)

    try:
        workspace = await prepare_workspace(job)
        await client.xadd(
            f"{EVENT_PREFIX}{run_id}",
            {"event": "run", "data": json.dumps({"status": "running"})},
        )
        permission = PermissionMode(job.get("permission_mode", "read_only"))
        approved = job.get("approved", "false").lower() == "true"
        ops_capabilities = _parse_ops_capabilities(job)
        ops_approved = bool(ops_capabilities)
        network_capabilities = _parse_network_capabilities(job)
        network_approved = bool(network_capabilities)
        tool_metadata = build_tool_metadata(
            model=getattr(runtime, "model", None),
            workspace=workspace,
            permission=permission,
            ops_approved=ops_approved,
            ops_capabilities=ops_capabilities,
            network_approved=network_approved,
            network_capabilities=network_capabilities,
            approved=approved,
            run_id=run_id,
            on_event=on_event,
        )
        # Rebind registry when experimental adapters are present for this job.
        registry = getattr(runtime, "registry", None)
        if tool_metadata and hasattr(runtime, "registry"):
            if registry is None or (
                registry.get("mcp") is None and registry.get("sub_agent") is None
            ):
                runtime.registry = build_default_registry(include_experimental=True)

        engine = (job.get("engine") or "langgraph").strip().lower()
        if engine == "metagpt":
            run_task = asyncio.create_task(
                run_metagpt_team(
                    job["prompt"],
                    workspace,
                    model=runtime.model,
                    permission=permission,
                    approved=approved,
                    ops_approved=ops_approved,
                    ops_capabilities=ops_capabilities,
                    network_approved=network_approved,
                    network_capabilities=network_capabilities,
                    roles_json=job.get("roles_json") or "",
                    run_id=run_id,
                    on_event=on_event,
                    registry=runtime.registry,
                    tool_metadata=tool_metadata or None,
                )
            )
        else:
            run_task = asyncio.create_task(
                runtime.run(
                    job["prompt"],
                    workspace,
                    RuntimeConfig(
                        permission=permission,
                        runner_backend=_runner_backend(permission),
                        approved=approved,
                        ops_approved=ops_approved,
                        ops_capabilities=ops_capabilities,
                        network_approved=network_approved,
                        network_capabilities=network_capabilities,
                        test_command=job.get("test_command") or None,
                        isolate_worktree=False,
                        workflow_definition=(
                            json.loads(job["workflow_definition"])
                            if job.get("workflow_definition")
                            else None
                        ),
                        workflow_version=(
                            int(job["workflow_version"]) if job.get("workflow_version") else None
                        ),
                        on_event=on_event,
                        tool_metadata=tool_metadata or None,
                    ),
                    run_id=run_id,
                )
            )
        interrupted = False
        while not run_task.done():
            if await _should_stop(client, run_id):
                run_task.cancel()
                try:
                    await run_task
                except asyncio.CancelledError:
                    # Only mark interrupted when cancel actually took effect.
                    # A race where the run finished before cancel must keep the real result.
                    payload = {
                        "run_id": run_id,
                        "status": "interrupted",
                        "summary": "Run interrupted by operator.",
                        "task_type": "explore",
                        "plan": [],
                        "artifacts": [],
                        "test_command": job.get("test_command") or None,
                        "test_exit_code": None,
                        "diff": "",
                        "events": [],
                        "error": "interrupted",
                    }
                    interrupted = True
                break
            await asyncio.wait({run_task}, timeout=0.5)
        if not interrupted:
            result = run_task.result()
            payload = result.model_dump(mode="json")
            # Live path already streamed events; avoid duplicate fan-out.
            payload["events"] = [
                event
                for event in payload.get("events", [])
                if int(event.get("sequence") or 0) not in live_sequences
            ]
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
            "error": _safe_error(exc),
        }
    await publish_result(
        client,
        run_id,
        payload,
        terminal_already_published="run_finished" in live_event_names,
    )
    await post_result(run_id, payload)
    await client.delete(f"{CONTROL_PREFIX}{run_id}")


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
                except PermissionError as exc:
                    logging.warning(
                        "discarding unauthorized worker job %s: %s",
                        message_id,
                        _safe_error(exc),
                    )
                    await client.xack(QUEUE, GROUP, message_id)
                    continue
                except Exception as exc:
                    # Leave the message pending so another delivery can retry the callback.
                    logging.error(
                        "worker job %s failed before acknowledgement: %s",
                        message_id,
                        _safe_error(exc),
                    )
                    continue
                await client.xack(QUEUE, GROUP, message_id)


if __name__ == "__main__":
    asyncio.run(serve())
