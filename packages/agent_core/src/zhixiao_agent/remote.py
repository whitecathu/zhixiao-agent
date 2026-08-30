from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

import httpx

TERMINAL_STATUSES = {
    "succeeded",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
    "awaiting_approval",
}
TERMINAL_EVENTS = {
    "result",
    "run.finished",
    "run_finished",
    "run.failed",
    "run.interrupted",
    "approval_required",
    "task_end",
    "error",
}


class RemoteError(RuntimeError):
    pass


@dataclass(frozen=True)
class ServerEvent:
    id: str | None
    event: str
    data: dict[str, Any]


async def parse_sse(lines: AsyncIterator[str]) -> AsyncIterator[ServerEvent]:
    event_id: str | None = None
    event_name = "message"
    data_lines: list[str] = []
    async for line in lines:
        if line == "":
            if data_lines:
                raw = "\n".join(data_lines)
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise RemoteError(f"invalid SSE JSON payload: {exc}") from exc
                if not isinstance(payload, dict):
                    payload = {"value": payload}
                yield ServerEvent(event_id, event_name, payload)
            event_id, event_name, data_lines = None, "message", []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "id":
            event_id = value
        elif field == "event":
            event_name = value
        elif field == "data":
            data_lines.append(value)
    if data_lines:
        raw = "\n".join(data_lines)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RemoteError(f"invalid SSE JSON payload: {exc}") from exc
        yield ServerEvent(
            event_id,
            event_name,
            payload if isinstance(payload, dict) else {"value": payload},
        )


class RemoteClient:
    def __init__(
        self,
        api_url: str,
        *,
        token: str | None = None,
        space_id: int = 1,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        normalized = api_url.rstrip("/")
        self.base = normalized if normalized.endswith("/api/v1") else normalized + "/api/v1"
        self.headers = {"X-Space-Id": str(space_id)}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        self.transport = transport
        self.last_run_id: str | None = None

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=httpx.Timeout(30),
            transport=self.transport,
        ) as client:
            try:
                response = await client.request(method, f"{self.base}{path}", **kwargs)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                try:
                    api_data(exc.response)
                except RemoteError as envelope_error:
                    detail = str(envelope_error)
                else:
                    detail = "request failed"
                raise RemoteError(
                    f"remote API {exc.response.status_code} for {method} {path}: {detail}"
                ) from exc
            except httpx.HTTPError as exc:
                raise RemoteError(f"remote API request failed: {exc}") from exc
            return api_data(response)

    async def create_run(
        self,
        prompt: str,
        permission: str,
        repository_id: int,
        *,
        budget: dict[str, Any] | None = None,
        allow_unverified: str | None = None,
        verification_commands: list[str] | None = None,
        session_name: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "repository_id": repository_id,
            "title": (prompt.strip().splitlines() or ["Untitled task"])[0][:255],
            "prompt": prompt,
            "permission_mode": permission,
        }
        if budget is not None:
            payload["budget"] = budget
        if allow_unverified is not None:
            payload["allow_unverified"] = allow_unverified
        if verification_commands:
            payload["verification_commands"] = verification_commands
        if session_name is not None:
            payload["session_name"] = session_name
        created = cast(dict[str, Any], await self.request("POST", "/task-runs", json=payload))
        self.last_run_id = str(created["id"])
        return created

    async def get_run(self, run_id: str | int) -> dict[str, Any]:
        return cast(dict[str, Any], await self.request("GET", f"/task-runs/{run_id}"))

    async def list_runs(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], await self.request("GET", "/task-runs"))

    async def fork(
        self, run_id: str | int, overrides: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self.request(
                "POST",
                f"/task-runs/{run_id}/fork",
                json=overrides or {},
            ),
        )

    async def approvals(self, run_id: str | int) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]], await self.request("GET", f"/task-runs/{run_id}/approvals")
        )

    async def decide(self, approval_id: str | int, approved: bool) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self.request(
                "POST",
                f"/approvals/{approval_id}/decision",
                json={"decision": "approved" if approved else "rejected"},
            ),
        )

    async def interrupt(self, run_id: str | int) -> dict[str, Any]:
        return cast(
            dict[str, Any], await self.request("POST", f"/task-runs/{run_id}/interrupt")
        )

    async def resume(self, run_id: str | int) -> dict[str, Any]:
        return cast(dict[str, Any], await self.request("POST", f"/task-runs/{run_id}/resume"))

    async def artifacts(self, run_id: str | int) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]], await self.request("GET", f"/task-runs/{run_id}/artifacts")
        )

    async def diff(self, run_id: str | int) -> dict[str, Any]:
        return cast(dict[str, Any], await self.request("GET", f"/task-runs/{run_id}/diff"))

    async def follow(
        self,
        run_id: str | int,
        *,
        cursor: str | None = None,
        wait_timeout: float = 900,
        on_event: Callable[[ServerEvent], Awaitable[None]] | None = None,
        retries: int = 4,
    ) -> dict[str, Any]:
        last_id = cursor
        seen: set[str] = set()
        started = asyncio.get_running_loop().time()
        attempt = 0
        while True:
            remaining = wait_timeout - (asyncio.get_running_loop().time() - started)
            if remaining <= 0:
                raise TimeoutError(f"timed out waiting for remote run {run_id}")
            headers = dict(self.headers)
            if last_id:
                headers["Last-Event-ID"] = last_id
            params = {"cursor": last_id} if last_id else None
            try:
                timeout = httpx.Timeout(30, read=min(45, remaining))
                async with httpx.AsyncClient(
                    headers=headers, timeout=timeout, transport=self.transport
                ) as client:
                    async with client.stream(
                        "GET", f"{self.base}/task-runs/{run_id}/events", params=params
                    ) as response:
                        response.raise_for_status()
                        async for event in parse_sse(response.aiter_lines()):
                            if event.id and event.id in seen:
                                continue
                            if event.id:
                                seen.add(event.id)
                                last_id = event.id
                            if on_event:
                                await on_event(event)
                            status = str(event.data.get("status", ""))
                            if event.event in TERMINAL_EVENTS or status in TERMINAL_STATUSES:
                                current = await self.get_run(run_id)
                                if str(current.get("status")) in TERMINAL_STATUSES:
                                    return current
                current = await self.get_run(run_id)
                if str(current.get("status")) in TERMINAL_STATUSES | {"awaiting_approval"}:
                    return current
                attempt = 0
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500 and exc.response.status_code != 429:
                    raise RemoteError(
                        f"event stream rejected with HTTP {exc.response.status_code}"
                    ) from exc
                attempt += 1
                if attempt > retries:
                    raise RemoteError(
                        f"event stream failed after {retries} retries: {exc}"
                    ) from exc
                await asyncio.sleep(min(2 ** (attempt - 1), 8))
            except (httpx.HTTPError, RemoteError) as exc:
                attempt += 1
                if attempt > retries:
                    raise RemoteError(
                        f"event stream failed after {retries} retries: {exc}"
                    ) from exc
                await asyncio.sleep(min(2 ** (attempt - 1), 8))


def api_data(response: httpx.Response) -> Any:
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise RemoteError("remote API returned a non-JSON response") from exc
    if not isinstance(payload, dict) or payload.get("code") != 0:
        trace_id = payload.get("trace_id") if isinstance(payload, dict) else None
        message = (
            payload.get("message") or payload.get("msg") or "invalid response envelope"
            if isinstance(payload, dict)
            else "invalid response envelope"
        )
        suffix = f" (trace_id={trace_id})" if trace_id else ""
        raise RemoteError(f"remote API error: {message}{suffix}")
    return payload.get("data")
