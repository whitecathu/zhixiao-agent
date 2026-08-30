from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import pytest

from zhixiao_agent.remote import RemoteClient, RemoteError, api_data, parse_sse


async def lines(*values: str) -> AsyncIterator[str]:
    for value in values:
        yield value


@pytest.mark.asyncio
async def test_sse_parser_supports_comments_ids_and_multiline_data() -> None:
    events = [
        item
        async for item in parse_sse(
            lines(
                ": heartbeat",
                "id: 7-0",
                "event: run.finished",
                'data: {"status":',
                'data: "succeeded"}',
                "",
            )
        )
    ]

    assert len(events) == 1
    assert events[0].id == "7-0"
    assert events[0].event == "run.finished"
    assert events[0].data == {"status": "succeeded"}


@pytest.mark.asyncio
async def test_remote_client_normalizes_api_prefix_and_uses_rejected_decision() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"code": 0, "data": {"id": 4, "status": "rejected"}},
        )

    client = RemoteClient(
        "https://agent.test/api/v1",
        transport=httpx.MockTransport(handler),
    )
    await client.decide(4, False)

    assert str(requests[0].url) == "https://agent.test/api/v1/approvals/4/decision"
    assert json.loads(requests[0].content) == {"decision": "rejected"}


@pytest.mark.asyncio
async def test_remote_create_run_forwards_budget_and_verification_controls() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"code": 0, "data": {"id": 9, "status": "awaiting_approval"}},
        )

    client = RemoteClient("https://agent.test", transport=httpx.MockTransport(handler))
    await client.create_run(
        "implement and test feature",
        "full",
        3,
        budget={"max_model_turns": 4, "max_tool_calls": 8, "max_tokens": 900},
        allow_unverified="manual integration environment",
        verification_commands=["pytest -q"],
    )

    payload = json.loads(requests[0].content)
    assert payload["budget"]["max_model_turns"] == 4
    assert payload["allow_unverified"] == "manual integration environment"
    assert payload["verification_commands"] == ["pytest -q"]
    assert client.last_run_id == "9"


@pytest.mark.asyncio
async def test_remote_follow_deduplicates_event_ids_and_fetches_terminal_run() -> None:
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/events"):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=(
                    'id: 1-0\nevent: step\ndata: {"status":"running"}\n\n'
                    'id: 1-0\nevent: step\ndata: {"status":"running"}\n\n'
                    'id: 2-0\nevent: run.finished\ndata: {"status":"succeeded"}\n\n'
                ),
            )
        return httpx.Response(
            200,
            json={"code": 0, "data": {"id": 8, "status": "succeeded"}},
        )

    async def receive(event) -> None:
        seen.append(event.id)

    client = RemoteClient("https://agent.test", transport=httpx.MockTransport(handler))
    result = await client.follow(8, on_event=receive, wait_timeout=2)

    assert seen == ["1-0", "2-0"]
    assert result["status"] == "succeeded"


@pytest.mark.asyncio
async def test_remote_follow_returns_when_approval_is_required() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/events"):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=(
                    "id: 3-0\n"
                    "event: approval_required\n"
                    'data: {"status":"awaiting_approval"}\n\n'
                ),
            )
        return httpx.Response(
            200,
            json={"code": 0, "data": {"id": 8, "status": "awaiting_approval"}},
        )

    client = RemoteClient("https://agent.test", transport=httpx.MockTransport(handler))
    result = await client.follow(8, wait_timeout=2)

    assert result["status"] == "awaiting_approval"


def test_remote_envelope_error_reports_message_without_dumping_payload() -> None:
    response = httpx.Response(
        422,
        json={"code": 1001, "message": "invalid prompt", "trace_id": "trace-7"},
    )

    with pytest.raises(RemoteError, match="invalid prompt.*trace-7"):
        api_data(response)


@pytest.mark.asyncio
async def test_resume_remote_follows_with_wait_timeout_and_on_event() -> None:
    from zhixiao_agent.cli import _resume_remote

    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/resume"):
            return httpx.Response(
                200,
                json={"code": 0, "data": {"id": 8, "status": "running"}},
            )
        if request.url.path.endswith("/events"):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text='id: 1-0\nevent: run.finished\ndata: {"status":"succeeded"}\n\n',
            )
        return httpx.Response(
            200,
            json={"code": 0, "data": {"id": 8, "status": "succeeded"}},
        )

    async def receive(event) -> None:
        seen.append(event.id)

    client = RemoteClient("https://agent.test", transport=httpx.MockTransport(handler))
    result = await _resume_remote(client, "8", wait_timeout=2, on_event=receive)

    assert seen == ["1-0"]
    assert result["status"] == "succeeded"


@pytest.mark.asyncio
async def test_fork_remote_follows_until_terminal() -> None:
    from zhixiao_agent.cli import _fork_remote

    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/fork"):
            return httpx.Response(
                200,
                json={"code": 0, "data": {"id": 12, "status": "running"}},
            )
        if request.url.path.endswith("/events"):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text='id: 4-0\nevent: run.finished\ndata: {"status":"succeeded"}\n\n',
            )
        return httpx.Response(
            200,
            json={"code": 0, "data": {"id": 12, "status": "succeeded"}},
        )

    client = RemoteClient("https://agent.test", transport=httpx.MockTransport(handler))
    result = await _fork_remote(client, "9", {"prompt": "continue"}, wait_timeout=2)

    assert result["status"] == "succeeded"
    assert any(path.endswith("/fork") for path in paths)
    assert any(path.endswith("/events") for path in paths)


@pytest.mark.asyncio
async def test_approve_remote_follows_original_run_when_payload_has_no_id() -> None:
    from zhixiao_agent.cli import _approve_remote

    followed: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/decision"):
            return httpx.Response(
                200,
                json={"code": 0, "data": {"ok": True}},
            )
        if request.url.path.endswith("/events"):
            followed.append(request.url.path)
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text='id: 2-0\nevent: run.finished\ndata: {"status":"succeeded"}\n\n',
            )
        return httpx.Response(
            200,
            json={"code": 0, "data": {"id": 8, "status": "succeeded"}},
        )

    client = RemoteClient("https://agent.test", transport=httpx.MockTransport(handler))
    result = await _approve_remote(client, "8", "4", True, wait_timeout=2)

    assert result["status"] == "succeeded"
    assert followed == ["/api/v1/task-runs/8/events"]
