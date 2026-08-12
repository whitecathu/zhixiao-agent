"""Message bus and role registry."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .message import Message
from .role import BaseRole


class Environment:
    def __init__(self) -> None:
        self.roles: dict[str, Any] = {}
        self.message_queue: list[Message] = []
        self.message_history: dict[str, list[Message]] = defaultdict(list)
        self._consumed_cursors: dict[str, int] = {}

    def add_role(self, role: Any) -> None:
        self.roles[role.name] = role
        self._consumed_cursors.setdefault(role.name, 0)

    def remove_role(self, role_name: str) -> None:
        if role_name in self.roles:
            del self.roles[role_name]
        self.message_history.pop(role_name, None)
        self._consumed_cursors.pop(role_name, None)

    def publish_message(self, msg: Message, publicer: str) -> None:
        msg.sent_from = publicer
        self.message_queue.append(msg)
        self.message_history[publicer].append(msg)

    def get_messages_for_role(self, role_name: str) -> list[Message]:
        role: BaseRole | None = self.roles.get(role_name)
        if not role:
            return []
        cursor = self._consumed_cursors.get(role_name, 0)
        pending = self.message_queue[cursor:]
        watch = role.watch
        if not watch:
            return [message for message in pending if message.sent_from != role_name]
        return [
            message
            for message in pending
            if message.sent_from != role_name and message.sent_from in watch
        ]

    def consume_messages_for_role(self, role_name: str) -> list[Message]:
        messages = self.get_messages_for_role(role_name)
        self._consumed_cursors[role_name] = len(self.message_queue)
        return messages

    def clear_queue(self) -> None:
        self.message_queue.clear()
        self._consumed_cursors = {name: 0 for name in self.roles}
