"""Replayable event broker tests."""
from __future__ import annotations

import pytest

from app.core.events import EventBroker, RedisStreamEventStore
from app.core.redis_client import RedisClient


@pytest.mark.asyncio
async def test_event_broker_replays_from_cursor():
    broker = EventBroker.memory()
    first = await broker.publish("run-1", "run.created", {"status": "pending"})
    second = await broker.publish("run-1", "run.started", {"status": "running"})

    all_events = await broker.read("run-1", after="0-0", block_ms=0)
    assert [item.event for item in all_events] == ["run.created", "run.started"]
    replay = await broker.read("run-1", after=first.id, block_ms=0)
    assert [item.id for item in replay] == [second.id]


@pytest.mark.asyncio
async def test_memory_broker_waits_for_new_event():
    broker = EventBroker.memory()

    async def publish_later():
        import asyncio
        await asyncio.sleep(0)
        await broker.publish("run-wait", "step.started", {"step": 1})

    import asyncio
    task = asyncio.create_task(publish_later())
    events = await broker.read("run-wait", after="0-0", block_ms=100)
    await task
    assert events[0].event == "step.started"
    assert await broker.read("missing", after="0-0", block_ms=1) == []


@pytest.mark.asyncio
async def test_redis_stream_store_serializes_events(monkeypatch):
    class FakeRedis:
        async def xadd(self, stream, fields, **kwargs):
            self.stream = stream
            self.fields = fields
            return "7-0"

        async def xread(self, streams, **kwargs):
            return [("run:events:run-redis", [("7-0", self.fields)])]

    fake = FakeRedis()

    async def get_fake(cls):
        return fake

    monkeypatch.setattr(RedisClient, "get", classmethod(get_fake))
    store = RedisStreamEventStore()
    published = await store.publish("run-redis", "run.started", {"status": "running"})
    replay = await store.read("run-redis", "0-0", 0)
    assert published.id == "7-0"
    assert replay == [published]
