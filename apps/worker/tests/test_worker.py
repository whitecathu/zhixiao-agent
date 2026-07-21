from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main as worker  # noqa: E402


class FakeRedis:
    def __init__(self) -> None:
        self.streams: dict[str, list[dict[str, str]]] = {}
        self.hashes: dict[str, dict[str, str]] = {}

    async def xadd(self, stream, fields, **kwargs):
        self.streams.setdefault(stream, []).append(fields)
        return f"{len(self.streams[stream])}-0"

    async def hset(self, key, mapping):
        self.hashes[key] = dict(mapping)

    async def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)


def test_normalize_event_projects_web_contract():
    projected = worker.normalize_event(
        {
            "event": "tool_result",
            "data": {"tool": "run_tests", "status": "succeeded", "summary": "8 passed"},
        }
    )
    assert [item[0] for item in projected] == ["tool", "terminal"]
    assert projected[1][1]["line"] == "run_tests: 8 passed"


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
async def test_prepare_workspace_rejects_unapproved_network_clone(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_BASE", str(tmp_path))
    with pytest.raises(PermissionError, match="approved network operation"):
        await worker.prepare_workspace(
            {
                "run_id": "2",
                "clone_url": "https://example.invalid/private.git",
                "default_branch": "main",
                "network_approved": "false",
            }
        )
