"""Team hire / disband / run loop."""

from __future__ import annotations

from .environment import Environment
from .memory import Memory
from .message import Message
from .role import ActionOutput, BaseRole


class Team:
    def __init__(self, memory: Memory | None = None):
        self.roles: dict[str, BaseRole] = {}
        self.env: Environment = Environment()
        self.memory: Memory = memory or Memory()
        self._next_role_index = 0

    def hire(self, roles: list[BaseRole]) -> None:
        for role in roles:
            self.roles[role.name] = role
            self.env.add_role(role)

    def disband(self, role_names: list[str]) -> None:
        for name in role_names:
            self.roles.pop(name, None)
            self.env.remove_role(name)

    async def run(self, task: str, max_iterations: int = 10) -> dict[str, ActionOutput]:
        self._next_role_index = 0
        initial = Message(content=task, role="user", cause_by="UserRequirement")
        self.env.publish_message(initial, publicer="user")

        results: dict[str, ActionOutput] = {}
        for _ in range(max_iterations):
            nxt = self._get_next_role()
            if nxt is None:
                break
            msgs = self.env.consume_messages_for_role(nxt.name)
            if not msgs:
                continue
            out = await nxt.run(msgs[-1])
            if out:
                results[nxt.name] = out
                self.memory.add(
                    Message(
                        content=out.result,
                        role="assistant",
                        sent_from=nxt.name,
                        cause_by=type(nxt).__name__,
                    )
                )
                self.env.publish_message(
                    Message(
                        content=str(out.result),
                        role="assistant",
                        sent_from=nxt.name,
                        cause_by=type(nxt).__name__,
                    ),
                    publicer=nxt.name,
                )
        self.env.clear_queue()
        return results

    def _get_next_role(self) -> BaseRole | None:
        roles = list(self.roles.values())
        if not roles:
            return None
        for offset in range(len(roles)):
            index = (self._next_role_index + offset) % len(roles)
            role = roles[index]
            if self.env.get_messages_for_role(role.name):
                self._next_role_index = (index + 1) % len(roles)
                return role
        return None
