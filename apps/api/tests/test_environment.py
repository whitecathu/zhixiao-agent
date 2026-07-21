"""tests/test_environment.py
MetaGPT Environment 消息路由单测
"""
import pytest

from app.environments.environment import Environment
from app.roles.base_role import BaseRole
from app.schemas.message import Message


class EchoRole(BaseRole):
    name: str = "echo"
    profile: str = "echo"
    goal: str = "echo"

    async def _think(self) -> bool:
        return True

    async def _act(self):
        from app.roles.base_role import ActionOutput
        return ActionOutput(result="echo-ok")


class WatcherRole(BaseRole):
    name: str = "watcher"
    profile: str = "watcher"
    goal: str = "watcher"
    watch: list = ["echo"]

    async def _think(self) -> bool:
        return True

    async def _act(self):
        from app.roles.base_role import ActionOutput
        return ActionOutput(result="watched")


@pytest.mark.asyncio
async def test_environment_message_routing():
    env = Environment()
    env.add_role(EchoRole())
    env.add_role(WatcherRole())
    # 初始消息
    env.publish_message(Message(content="hello", cause_by="UserRequirement"), publicer="user")
    # echo 没有设置 watch，会收到所有消息
    assert len(env.get_messages_for_role("echo")) == 1
    # watcher 没有 echo 来源的消息时不触发
    assert len(env.get_messages_for_role("watcher")) == 0

    # echo 发消息
    env.publish_message(Message(content="reply", cause_by="echo"), publicer="echo")
    assert len(env.get_messages_for_role("watcher")) == 1


@pytest.mark.asyncio
async def test_team_full_cycle_run():
    from app.teams.team import Team

    class HelloRole(BaseRole):
        name: str = "hello"
        profile: str = "hello"
        goal: str = "hello"

        async def _think(self) -> bool:
            return True

        async def _act(self):
            from app.roles.base_role import ActionOutput
            return ActionOutput(result="hello-world")

    team = Team()
    team.hire([HelloRole()])
    res = await team.run("greet", max_iterations=3)
    assert "hello" in res
    assert res["hello"].result == "hello-world"