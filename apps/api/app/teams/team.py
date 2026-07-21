"""app/teams/team.py
MetaGPT Team 模式 - 角色雇佣 / 解雇 / 任务执行循环
"""

from typing import Dict, Optional

from app.environments.environment import Environment
from app.memory.memory import Memory
from app.roles.base_role import ActionOutput, BaseRole
from app.schemas.message import Message


class Team:
    """团队管理 - 参考脚本内的 MetaGPT Team 设计"""

    def __init__(self, memory: Optional[Memory] = None):
        self.roles: Dict[str, BaseRole] = {}
        self.env: Environment = Environment()
        self.memory: Memory = memory or Memory()

    def hire(self, roles: list[BaseRole]) -> None:
        for r in roles:
            self.roles[r.name] = r
            self.env.add_role(r)

    def disband(self, role_names: list[str]) -> None:
        for name in role_names:
            self.roles.pop(name, None)
            self.env.remove_role(name)

    async def run(self, task: str, max_iterations: int = 10) -> Dict[str, ActionOutput]:
        initial = Message(content=task, role="user", cause_by="UserRequirement")
        self.env.publish_message(initial, publicer="user")

        results: Dict[str, ActionOutput] = {}
        for _ in range(max_iterations):
            nxt = self._get_next_role()
            if nxt is None:
                break
            msgs = self.env.get_messages_for_role(nxt.name)
            if not msgs:
                break
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

    def _get_next_role(self) -> Optional[BaseRole]:
        for r in self.roles.values():
            if self.env.get_messages_for_role(r.name):
                return r
        return None
