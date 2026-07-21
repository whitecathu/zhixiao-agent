"""app/roles/base_role.py
MetaGPT Role 模式 - 角色基类
生命周期：_observe → _think → _act；通过 Environment 消息驱动
"""

from abc import ABC, abstractmethod
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.message import Message


class ActionOutput(BaseModel):
    """动作输出标准化"""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    code: str = ""
    result: Any = None
    is_success: bool = True
    metadata: dict = Field(default_factory=dict)


class BaseRole(BaseModel, ABC):
    """角色基类 - 参考脚本内的 MetaGPT Role 设计"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    profile: str
    goal: str
    tools: list[str] = Field(default_factory=list)
    watch: list[str] = Field(default_factory=list)
    state: dict = Field(default_factory=dict)

    @abstractmethod
    async def _think(self) -> bool:
        """思考：基于最近观察决定是否需要执行"""
        ...

    @abstractmethod
    async def _act(self) -> ActionOutput:
        """执行：实际产出"""
        ...

    async def _observe(self, message: Message) -> bool:
        """观察：处理接收到的消息，返回是否触发执行"""
        self.state["last_message"] = message
        # 默认行为：消息发送方在 watch 列表内或 watch 为空都触发
        if not self.watch or message.sent_from in self.watch:
            return True
        return False

    async def run(self, message: Optional[Message] = None) -> Optional[ActionOutput]:
        """运行角色（默认按 observe→think→act 顺序）"""
        if message is not None:
            should_act = await self._observe(message)
            if not should_act:
                return None
        think_ok = await self._think()
        if not think_ok:
            return None
        return await self._act()
