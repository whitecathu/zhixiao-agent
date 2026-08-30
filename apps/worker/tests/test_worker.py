from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main as worker  # noqa: E402

from zhixiao_agent.job_security import (
    ISSUED_AT_FIELD,
    NONCE_FIELD,
    SIGNATURE_FIELD,
    sign_job_fields,
)

ECHO_PLUGIN = """
from pydantic import BaseModel

from zhixiao_agent.plugin import PluginContext
from zhixiao_agent.tools.base import BaseTool
from zhixiao_agent.types import ToolResult

name = "echo"
inject = ("tools",)

class EchoInput(BaseModel):
    text: str = ""

class EchoTool(BaseTool):
    name = "echo_plugin"
    description = "Echo text from a workspace plugin"
    input_model = EchoInput

    async def execute(self, arguments, context):
        del context
        return ToolResult.ok(arguments.get("text") or "")

def apply(ctx: PluginContext) -> None:
    ctx.register_tool(EchoTool())
    ctx.register_command(
        "echo",
        description="Expand an echo prompt",
        template="Echo {{args}}",
        mode="ask",
    )
    ctx.register_prompt_section("echo", "You may call echo_plugin.")
    ctx.on("run/start", lambda payload: payload.setdefault("seen", True))
"""


def _write_echo_plugin(workspace: Path) -> Path:
    directory = workspace / ".zhixiao" / "plugins"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "echo.py"
    path.write_text(ECHO_PLUGIN, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def managed_workspace_root(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_BASE", str(tmp_path))
    monkeypatch.setenv("WORKSPACE_SOURCE_ROOTS", str(tmp_path))
    monkeypatch.setenv("ZHIXIAO_CONFIG_FILE", str(tmp_path / "user-config.toml"))


class FakeRedis:
    def __init__(self) -> None:
        self.streams: dict[str, list[dict[str, str]]] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.values: dict[str, str] = {}

    async def xadd(self, stream, fields, **kwargs):
        self.streams.setdefault(stream, []).append(fields)
        return f"{len(self.streams[stream])}-0"

    async def hset(self, key, mapping):
        self.hashes[key] = dict(mapping)

    async def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None):
        self.values[key] = value
        return True

    async def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)
            self.hashes.pop(key, None)
        return len(keys)


def test_build_tool_metadata_includes_mcp_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("MCP_WHITELIST", "local:read")
    monkeypatch.setenv("MCP_LOCAL_HANDLERS", '{"local:read": {"ok": true}}')
    monkeypatch.setenv("SUBAGENT_ENABLED", "true")
    from zhixiao_agent.model import ModelProfile, OpenAICompatibleModel

    model = OpenAICompatibleModel(
        ModelProfile(provider="x", model="y", api_base="http://localhost", api_key="k")
    )

    async def on_event(_event):
        return None

    meta = worker.build_tool_metadata(
        model=model,
        workspace=tmp_path,
        permission=worker.PermissionMode.FULL,
        ops_approved=True,
        ops_capabilities=frozenset({"mcp", "sub_agent"}),
        network_approved=False,
        network_capabilities=frozenset(),
        approved=True,
        run_id="1",
        on_event=on_event,
    )
    assert "mcp" in meta
    assert meta["mcp_whitelist"] == ["local:read"]
    assert "sub_agent" in meta


def test_normalize_event_projects_web_contract():
    projected = worker.normalize_event(
        {
            "event": "tool_result",
            "data": {"tool": "run_tests", "status": "succeeded", "summary": "8 passed"},
        }
    )
    assert [item[0] for item in projected] == ["tool", "terminal"]
    assert projected[1][1]["line"] == "run_tests: 8 passed"


def test_worker_rejects_tampered_signed_job(monkeypatch):
    secret = "worker-signing-secret-at-least-32-characters"
    monkeypatch.setenv("WORKER_JOB_SIGNING_SECRET", secret)
    fields = {
        "run_id": "signed-1",
        "prompt": "inspect",
        "permission_mode": "read_only",
        "engine": "langgraph",
        ISSUED_AT_FIELD: str(int(time.time())),
        NONCE_FIELD: "a" * 32,
    }
    fields[SIGNATURE_FIELD] = sign_job_fields(fields, secret)
    worker._verify_job(fields)
    fields["permission_mode"] = "full"
    with pytest.raises(PermissionError, match="signature"):
        worker._verify_job(fields)


def test_build_runtime_reads_cost_env(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_INPUT_COST_PER_MILLION", "1.5")
    monkeypatch.setenv("LLM_OUTPUT_COST_PER_MILLION", "2.5")
    runtime = worker.build_runtime()
    profile = runtime.model.profile
    assert profile.input_cost_per_million == 1.5
    assert profile.output_cost_per_million == 2.5


def test_build_runtime_defaults_cost_when_unset(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.delenv("LLM_INPUT_COST_PER_MILLION", raising=False)
    monkeypatch.delenv("LLM_OUTPUT_COST_PER_MILLION", raising=False)
    runtime = worker.build_runtime()
    profile = runtime.model.profile
    assert profile.input_cost_per_million == 0.0
    assert profile.output_cost_per_million == 0.0


def test_build_runtime_enables_experimental_registry_for_mcp_whitelist(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("MCP_WHITELIST", "local:read")
    monkeypatch.delenv("SUBAGENT_ENABLED", raising=False)
    runtime = worker.build_runtime()
    assert runtime.registry.get("mcp") is not None
    assert runtime.registry.get("sub_agent") is not None


def test_assemble_job_registry_skips_untrusted_workspace_plugin(tmp_path):
    _write_echo_plugin(tmp_path)
    registry = worker.assemble_job_registry(
        tmp_path, trusted=False, include_experimental=False
    )
    assert registry.get("echo_plugin") is None


def test_assemble_job_registry_includes_trusted_workspace_plugin(tmp_path):
    _write_echo_plugin(tmp_path)
    registry = worker.assemble_job_registry(
        tmp_path, trusted=True, include_experimental=False
    )
    assert registry.get("echo_plugin") is not None


@pytest.mark.asyncio
async def test_process_job_loads_trusted_plugin_prompt(tmp_path, monkeypatch):
    _write_echo_plugin(tmp_path)
    client = FakeRedis()
    captured = []

    class Result:
        def model_dump(self, **kwargs):
            return {
                "run_id": "plugin-1",
                "status": "succeeded",
                "summary": "done",
                "events": [],
            }

    class Runtime:
        async def run(self, prompt, workspace, config, *, run_id):
            captured.append((self.registry, config))
            return Result()

    async def fake_post(*args, **kwargs):
        return None

    monkeypatch.setattr(worker, "post_result", fake_post)
    runtime = Runtime()
    await worker.process_job(
        client,
        runtime,
        {
            "run_id": "plugin-1",
            "prompt": "inspect plugins",
            "permission_mode": "read_only",
            "workspace": str(tmp_path),
            "trusted_workspace": "true",
        },
    )
    registry, config = captured[0]
    assert registry.get("echo_plugin") is not None
    assert "echo_plugin" in (config.plugin_prompt or "")


def test_build_tool_metadata_includes_mcp_handler(monkeypatch, tmp_path):
    monkeypatch.setenv("MCP_WHITELIST", "local:read")
    monkeypatch.setenv("MCP_HTTP_BASE", "http://127.0.0.1:9")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.delenv("SUBAGENT_ENABLED", raising=False)

    class DummyModel:
        pass

    metadata = worker.build_tool_metadata(
        model=DummyModel(),  # type: ignore[arg-type]
        workspace=tmp_path,
        permission=worker.PermissionMode.READ_ONLY,
        ops_approved=False,
        ops_capabilities=frozenset({"mcp"}),
        network_approved=False,
        network_capabilities=frozenset(),
        approved=False,
        run_id="run-1",
        on_event=None,
    )
    assert callable(metadata["mcp"])
    assert metadata["mcp_whitelist"] == ["local:read"]
    assert "sub_agent" not in metadata


@pytest.mark.asyncio
async def test_publish_result_uses_api_event_stream_key():
    client = FakeRedis()
    payload = {
        "status": "succeeded",
        "summary": "done",
        "events": [{"event": "run_started", "data": {"status": "running"}}],
    }
    await worker.publish_result(client, "42", payload)
    assert "run:events:42" in client.streams
    assert json.loads(client.streams["run:events:42"][-1]["data"])["status"] == "succeeded"
    assert json.loads(client.hashes["run:result:42"]["payload"])["summary"] == "done"


@pytest.mark.asyncio
async def test_cached_result_retries_callback_without_running_agent(monkeypatch):
    client = FakeRedis()
    payload = {"run_id": "9", "status": "succeeded", "summary": "cached"}
    client.hashes["run:result:9"] = {"payload": json.dumps(payload)}
    posted: list[tuple[str, dict]] = []

    async def fake_post(run_id, result):
        posted.append((run_id, result))

    class NeverRuntime:
        async def run(self, *args, **kwargs):
            raise AssertionError("cached deliveries must not execute the agent twice")

    monkeypatch.setattr(worker, "post_result", fake_post)
    await worker.process_job(client, NeverRuntime(), {"run_id": "9", "prompt": "unused"})
    assert posted == [("9", payload)]


@pytest.mark.asyncio
async def test_prepare_workspace_accepts_explicit_existing_path(tmp_path):
    prepared = await worker.prepare_workspace({"run_id": "1", "workspace": str(tmp_path)})
    assert prepared == tmp_path.resolve()


@pytest.mark.asyncio
async def test_prepare_workspace_rejects_path_outside_managed_root(tmp_path, monkeypatch):
    managed = tmp_path / "managed"
    managed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv("WORKSPACE_BASE", str(managed))
    with pytest.raises(PermissionError, match="escapes allowed roots"):
        await worker.prepare_workspace({"run_id": "escape", "workspace": str(outside)})


@pytest.mark.asyncio
async def test_prepare_workspace_rejects_unapproved_network_clone(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_BASE", str(tmp_path))
    with pytest.raises(PermissionError, match="explicit clone approval"):
        await worker.prepare_workspace(
            {
                "run_id": "2",
                "clone_url": "https://example.invalid/private.git",
                "default_branch": "main",
                "clone_approved": "false",
            }
        )


@pytest.mark.asyncio
async def test_prepare_workspace_rejects_local_or_option_injection_clone_urls(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("WORKSPACE_BASE", str(tmp_path))
    base_job = {
        "run_id": "clone-safe",
        "default_branch": "main",
        "clone_approved": "true",
    }
    for clone_url in ("file:///etc", "https://127.0.0.1/private.git", "--upload-pack=calc"):
        with pytest.raises(PermissionError):
            await worker.prepare_workspace({**base_job, "clone_url": clone_url})


def test_local_runner_is_refused_for_execute_without_explicit_dev_override(monkeypatch):
    monkeypatch.setenv("RUNNER_BACKEND", "local")
    monkeypatch.delenv("ALLOW_UNSANDBOXED_LOCAL_EXECUTION", raising=False)
    with pytest.raises(PermissionError, match="require RUNNER_BACKEND"):
        worker._runner_backend(worker.PermissionMode.EXECUTE)
    assert worker._runner_backend(worker.PermissionMode.READ_ONLY) == "local"


@pytest.mark.asyncio
async def test_process_job_supports_legacy_and_versioned_workflow_config(tmp_path, monkeypatch):
    client = FakeRedis()
    captured = []

    class Result:
        def model_dump(self, **kwargs):
            return {
                "run_id": "3",
                "status": "succeeded",
                "summary": "done",
                "events": [],
            }

    class Runtime:
        async def run(self, prompt, workspace, config, *, run_id):
            captured.append(config)
            return Result()

    async def fake_post(*args, **kwargs):
        return None

    monkeypatch.setattr(worker, "post_result", fake_post)
    await worker.process_job(
        client,
        Runtime(),
        {
            "run_id": "3",
            "prompt": "legacy job",
            "permission_mode": "read_only",
            "workspace": str(tmp_path),
        },
    )

    assert captured[0].workflow_definition is None
    assert captured[0].workflow_version is None

    workflow = {"nodes": [{"id": "review", "role": "reviewer"}], "edges": []}
    await worker.process_job(
        client,
        Runtime(),
        {
            "run_id": "4",
            "prompt": "versioned job",
            "permission_mode": "read_only",
            "workspace": str(tmp_path),
            "workflow_definition": json.dumps(workflow),
            "workflow_version": "3",
        },
    )
    assert captured[1].workflow_definition == workflow
    assert captured[1].workflow_version == 3


@pytest.mark.asyncio
async def test_process_job_passes_verification_budget_and_waiver(tmp_path, monkeypatch):
    client = FakeRedis()
    captured = []

    class Result:
        def model_dump(self, **kwargs):
            return {
                "run_id": "budget-1",
                "status": "succeeded",
                "summary": "done",
                "events": [],
            }

    class Runtime:
        async def run(self, prompt, workspace, config, *, run_id):
            captured.append(config)
            return Result()

    async def fake_post(*args, **kwargs):
        return None

    monkeypatch.setattr(worker, "post_result", fake_post)
    await worker.process_job(
        client,
        Runtime(),
        {
            "run_id": "budget-1",
            "prompt": "verify configured limits",
            "permission_mode": "read_only",
            "workspace": str(tmp_path),
            "allow_unverified": "CI image has no browser",
            "verification_commands": json.dumps(["pytest -q", "ruff check ."]),
            "max_model_turns": "7",
            "max_tool_calls": "11",
            "max_tokens": "12000",
            "max_cost_usd": "1.25",
            "max_duration_seconds": "300",
        },
    )

    config = captured[0]
    assert config.allow_unverified == "CI image has no browser"
    assert config.verification_commands == ("pytest -q", "ruff check .")
    assert config.budget.max_model_turns == 7
    assert config.budget.max_tool_calls == 11
    assert config.budget.max_tokens == 12000
    assert config.budget.max_cost_usd == 1.25
    assert config.budget.max_duration_seconds == 300


def test_runtime_budget_rejects_invalid_signed_values():
    with pytest.raises(PermissionError, match="max_tokens"):
        worker._runtime_budget({"max_tokens": "0"})
    with pytest.raises(PermissionError, match="verification_commands"):
        worker._parse_verification_commands({"verification_commands": "not-json"})


def test_terminal_payload_uses_the_versioned_result_contract():
    payload = worker._terminal_payload(
        "run-1",
        status="failed",
        summary="failed safely",
        error="boom",
        test_command=None,
        termination_reason="runtime_error",
    )
    assert payload["schema_version"] == "1.1"
    assert payload["verification"]["outcome"] == "blocked"
    assert payload["termination_reason"] == "runtime_error"
    assert payload["budgets"]["max_model_turns"] > 0
    assert payload["usage"]["tool_calls"] == 0


@pytest.mark.asyncio
async def test_process_job_honors_interrupt_control_flag(tmp_path, monkeypatch):
    client = FakeRedis()
    started = asyncio.Event()

    class SlowRuntime:
        async def run(self, *args, **kwargs):
            started.set()
            await asyncio.sleep(30)
            raise AssertionError("interrupted jobs must cancel before completion")

    posted: list[dict] = []

    async def fake_post(run_id, result):
        posted.append(result)

    monkeypatch.setattr(worker, "post_result", fake_post)

    async def arm_stop():
        await started.wait()
        client.values["run:control:77"] = "stop"

    arm = asyncio.create_task(arm_stop())
    await worker.process_job(
        client,
        SlowRuntime(),
        {
            "run_id": "77",
            "prompt": "slow",
            "permission_mode": "read_only",
            "workspace": str(tmp_path),
        },
    )
    await arm
    assert posted[0]["status"] == "interrupted"
    assert client.values.get("run:control:77") is None


@pytest.mark.asyncio
async def test_process_job_interrupt_race_keeps_finished_result(tmp_path, monkeypatch):
    """If the run finishes before cancel applies, keep the success payload."""
    client = FakeRedis()
    allow_finish = asyncio.Event()

    class RaceRuntime:
        async def run(self, *args, **kwargs):
            await allow_finish.wait()

            class Result:
                def model_dump(self, **kwargs):
                    return {
                        "run_id": "88",
                        "status": "succeeded",
                        "summary": "finished first",
                        "events": [],
                    }

            return Result()

    posted: list[dict] = []

    async def fake_post(run_id, result):
        posted.append(result)

    async def stop_then_finish(_client, _run_id):
        # Worker has decided to interrupt; finish the run before cancel lands.
        allow_finish.set()
        await asyncio.sleep(0)
        return True

    monkeypatch.setattr(worker, "post_result", fake_post)
    monkeypatch.setattr(worker, "_should_stop", stop_then_finish)

    await worker.process_job(
        client,
        RaceRuntime(),
        {
            "run_id": "88",
            "prompt": "race",
            "permission_mode": "read_only",
            "workspace": str(tmp_path),
        },
    )
    assert posted[0]["status"] == "succeeded"
    assert posted[0]["summary"] == "finished first"
