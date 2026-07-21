"""Backward-compatible SSE endpoint backed by the replayable event broker."""

import asyncio
import json

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse

from app.core.middleware import get_current_user
from app.core.events import EventBroker

router = APIRouter(prefix="/sse", tags=["SSE 执行流"])


@router.get("/tasks/{task_id}")
async def stream_task(
    task_id: int,
    request: Request,
    cursor: str | None = Query(default=None),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    user: dict = Depends(get_current_user),
):
    async def gen():
        broker = EventBroker.default()
        current = last_event_id or cursor or "0-0"
        while not await request.is_disconnected():
            events = await broker.read(str(task_id), after=current, block_ms=5_000)
            if not events:
                yield ": heartbeat\n\n"
                await asyncio.sleep(0)
                continue
            for event in events:
                current = event.id
                yield _format_event(event.event, event.data, event.id)

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",  # 关键：禁止 Nginx 缓冲
        "Connection": "keep-alive",
    }
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)


def _format_event(event: str, data, event_id: str | None = None) -> str:
    payload = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
    prefix = f"id: {event_id}\n" if event_id else ""
    return f"{prefix}event: {event}\ndata: {payload}\n\n"
