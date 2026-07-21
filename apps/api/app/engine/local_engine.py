"""In-process execution adapter used when no external worker has registered an engine."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from app.engine.abstract_engine import AbstractExecutionEngine, SSEEvent


class InProcessExecutionEngine(AbstractExecutionEngine):
    """Tracks lifecycle locally while a worker consumes the persisted task separately."""

    def __init__(self) -> None:
        self._states: dict[str, dict[str, Any]] = {}

    async def submit(self, task_id: str, goal: str, context: dict[str, Any]) -> str:
        execution_id = uuid.uuid4().hex
        self._states[execution_id] = {
            "task_id": task_id,
            "goal": goal,
            "context": context,
            "status": "running",
            "current_node": "START",
            "progress": 0,
        }
        return execution_id

    async def interrupt(self, execution_id: str) -> bool:
        state = self._states.get(execution_id)
        if not state or state["status"] != "running":
            return False
        state["status"] = "interrupted"
        return True

    async def resume(self, execution_id: str) -> bool:
        state = self._states.get(execution_id)
        if not state or state["status"] != "interrupted":
            return False
        state["status"] = "running"
        return True

    async def get_state(self, execution_id: str) -> dict[str, Any]:
        return dict(self._states.get(execution_id, {"status": "not_found"}))

    async def stream(self, execution_id: str) -> AsyncIterator[SSEEvent]:
        state = await self.get_state(execution_id)
        yield SSEEvent("run.state", state)
