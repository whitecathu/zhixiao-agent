"""Backward-compatible SSE endpoint gated by space membership and run ownership."""

import asyncio
import json

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.middleware import get_space_id
from app.core.events import EventBroker
from app.db.session import get_session
from app.service.platform_service import PlatformService

router = APIRouter(prefix="/sse", tags=["SSE 执行流（旧版）"], deprecated=True)


@router.get("/tasks/{task_id}")
async def stream_task(
    task_id: int,
    request: Request,
    cursor: str | None = Query(default=None),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    space_id: int = Depends(get_space_id),
    session: AsyncSession = Depends(get_session),
):
    """Legacy SSE path: requires space membership and that the run belongs to the space."""
    svc = PlatformService(session)
    await svc.get_run(task_id, space_id)

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
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
        "Deprecation": "true",
        "Warning": (
            '299 - "Deprecated SSE API: migrate to /api/v1/tasks/{id}/events"'
        ),
        "Link": f'</api/v1/tasks/{task_id}/events>; rel="successor-version"',
    }
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)


def _format_event(event: str, data, event_id: str | None = None) -> str:
    payload = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
    prefix = f"id: {event_id}\n" if event_id else ""
    return f"{prefix}event: {event}\ndata: {payload}\n\n"
