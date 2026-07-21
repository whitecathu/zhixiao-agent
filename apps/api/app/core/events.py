"""Replayable task-run events backed by Redis Streams or an in-memory test store."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import settings
from app.core.redis_client import RedisClient

RUN_EVENT_KEY_PREFIX = "run:events:"


@dataclass(frozen=True, slots=True)
class RunEvent:
    id: str
    event: str
    data: dict[str, Any]


class EventStore(Protocol):
    async def publish(self, run_id: str, event: str, data: dict[str, Any]) -> RunEvent: ...
    async def read(self, run_id: str, after: str, block_ms: int) -> list[RunEvent]: ...


class MemoryEventStore:
    def __init__(self) -> None:
        self._events: dict[str, list[RunEvent]] = {}
        self._conditions: dict[str, asyncio.Condition] = {}
        self._sequence = 0

    async def publish(self, run_id: str, event: str, data: dict[str, Any]) -> RunEvent:
        condition = self._conditions.setdefault(run_id, asyncio.Condition())
        async with condition:
            self._sequence += 1
            item = RunEvent(f"{self._sequence}-0", event, data)
            self._events.setdefault(run_id, []).append(item)
            condition.notify_all()
            return item

    async def read(self, run_id: str, after: str, block_ms: int) -> list[RunEvent]:
        def available() -> list[RunEvent]:
            cursor = int(after.split("-", 1)[0]) if after else 0
            return [
                item
                for item in self._events.get(run_id, [])
                if int(item.id.split("-", 1)[0]) > cursor
            ]

        events = available()
        if events or block_ms <= 0:
            return events
        condition = self._conditions.setdefault(run_id, asyncio.Condition())
        try:
            async with condition:
                await asyncio.wait_for(condition.wait(), timeout=block_ms / 1000)
        except TimeoutError:
            return []
        return available()


class RedisStreamEventStore:
    async def publish(self, run_id: str, event: str, data: dict[str, Any]) -> RunEvent:
        client = await RedisClient.get()
        event_id = await client.xadd(
            f"{RUN_EVENT_KEY_PREFIX}{run_id}",
            {"event": event, "data": json.dumps(data, ensure_ascii=False)},
            maxlen=10_000,
            approximate=True,
        )
        return RunEvent(str(event_id), event, data)

    async def read(self, run_id: str, after: str, block_ms: int) -> list[RunEvent]:
        client = await RedisClient.get()
        response = await client.xread(
            {f"{RUN_EVENT_KEY_PREFIX}{run_id}": after or "0-0"},
            count=100,
            block=block_ms or None,
        )
        events: list[RunEvent] = []
        for _, entries in response:
            for event_id, fields in entries:
                events.append(
                    RunEvent(
                        id=str(event_id),
                        event=fields["event"],
                        data=json.loads(fields["data"]),
                    )
                )
        return events


class EventBroker:
    _default: EventBroker | None = None

    def __init__(self, store: EventStore) -> None:
        self._store = store

    @classmethod
    def memory(cls) -> EventBroker:
        return cls(MemoryEventStore())

    @classmethod
    def default(cls) -> EventBroker:
        if cls._default is None:
            store: EventStore = (
                MemoryEventStore() if settings.APP_ENV == "test" else RedisStreamEventStore()
            )
            cls._default = cls(store)
        return cls._default

    async def publish(self, run_id: str, event: str, data: dict[str, Any]) -> RunEvent:
        return await self._store.publish(run_id, event, data)

    async def read(self, run_id: str, after: str = "0-0", block_ms: int = 0) -> list[RunEvent]:
        return await self._store.read(run_id, after, block_ms)
