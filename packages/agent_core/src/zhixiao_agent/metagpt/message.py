"""Environment message used by MetaGPT-style role teams."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Message(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    content: Any
    role: str = "user"
    sent_from: str = ""
    cause_by: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def __str__(self) -> str:
        return f"[Message from={self.sent_from} cause_by={self.cause_by}] {str(self.content)[:120]}"
