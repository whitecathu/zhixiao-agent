"""app/environments/environment.py
MetaGPT Environment 模式 - 消息总线与角色注册表
"""

from collections import defaultdict
from typing import Any, Dict, List, Optional

from app.roles.base_role import BaseRole
from app.schemas.message import Message


class Environment:
    """环境 - 参考脚本内的 MetaGPT Environment 设计"""

    def __init__(self) -> None:
        self.roles: Dict[str, Any] = {}
        self.message_queue: List[Message] = []
        self.message_history: Dict[str, List[Message]] = defaultdict(list)

    def add_role(self, role: Any) -> None:
        self.roles[role.name] = role

    def remove_role(self, role_name: str) -> None:
        if role_name in self.roles:
            del self.roles[role_name]
        self.message_history.pop(role_name, None)

    def publish_message(self, msg: Message, publicer: str) -> None:
        """发布消息并保证 sent_from 可追溯"""
        msg.sent_from = publicer
        self.message_queue.append(msg)
        self.message_history[publicer].append(msg)

    def get_messages_for_role(self, role_name: str) -> List[Message]:
        role: Optional[BaseRole] = self.roles.get(role_name)
        if not role:
            return []
        watch = role.watch
        if not watch:
            return list(self.message_queue)
        return [m for m in self.message_queue if m.sent_from in watch]

    def clear_queue(self) -> None:
        self.message_queue.clear()
