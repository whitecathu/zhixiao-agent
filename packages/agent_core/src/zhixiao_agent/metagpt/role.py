"""Role base class — observe → think → act."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .message import Message


class ActionOutput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    code: str = ""
    result: Any = None
    is_success: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class BaseRole(BaseModel, ABC):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    profile: str
    goal: str
    tools: list[str] = Field(default_factory=list)
    watch: list[str] = Field(default_factory=list)
    state: dict[str, Any] = Field(default_factory=dict)

    @abstractmethod
    async def _think(self) -> bool: ...

    @abstractmethod
    async def _act(self) -> ActionOutput: ...

    async def _observe(self, message: Message) -> bool:
        self.state["last_message"] = message
        if not self.watch or message.sent_from in self.watch:
            return True
        return False

    async def run(self, message: Message | None = None) -> ActionOutput | None:
        if message is not None:
            should_act = await self._observe(message)
            if not should_act:
                return None
        think_ok = await self._think()
        if not think_ok:
            return None
        return await self._act()
