"""app/schemas/message.py
MetaGPT 消息体 - 角色 / Agent / 团队间通信
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class Message(BaseModel):
    """环境消息 - 参考 MetaGPT Message"""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    content: Any  # 文本/结构化对象均可
    role: str = "user"  # user / assistant / system
    sent_from: str = ""  # 发送方 Role 名
    cause_by: str = ""  # 产生消息的 Action 类型名
    metadata: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def __str__(self) -> str:
        return f"[Message from={self.sent_from} cause_by={self.cause_by}] {str(self.content)[:120]}"
