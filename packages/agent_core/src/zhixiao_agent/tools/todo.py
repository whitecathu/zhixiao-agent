from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from ..types import TodoItem, ToolResult
from .base import BaseTool, ToolContext


class TodoUpdate(BaseModel):
    id: str
    content: str | None = None
    status: Literal["pending", "in_progress", "completed", "cancelled"] | None = None


class TodoInput(BaseModel):
    todos: list[TodoUpdate]
    replace: bool = False


class TodoTool(BaseTool):
    name = "todo"
    description = (
        "Create or update the visible structured task list; only one item may be in progress."
    )
    input_model = TodoInput

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        request = self.validate(arguments)
        raw = [] if request.replace else list(context.metadata.get("todos", []))
        items = {item["id"]: TodoItem.model_validate(item) for item in raw}
        for update in request.todos:
            current = items.get(update.id)
            if current is None:
                if not update.content:
                    return ToolResult.error(
                        "new todo requires content",
                        root_cause=update.id,
                        retry="provide content for the new todo",
                    )
                current = TodoItem(id=update.id, content=update.content)
            payload = current.model_dump()
            if update.content is not None:
                payload["content"] = update.content
            if update.status is not None:
                payload["status"] = update.status
            items[update.id] = TodoItem.model_validate(payload)
        if sum(item.status == "in_progress" for item in items.values()) > 1:
            return ToolResult.error(
                "multiple todos are in progress",
                root_cause="todo invariant violation",
                retry="keep exactly one item in progress",
            )
        serialized = [item.model_dump() for item in items.values()]
        context.metadata["todos"] = serialized
        return ToolResult.ok(f"stored {len(serialized)} todos", serialized)
