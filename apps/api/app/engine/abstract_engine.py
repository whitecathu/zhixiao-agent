"""app/engine/abstract_engine.py
AI 执行引擎抽象层 - 解耦业务层与本地/Worker 执行适配器。
"""

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, Optional


class SSEEvent:
    """统一的 SSE 事件结构"""

    __slots__ = ("event", "data")

    def __init__(self, event: str, data: Any):
        self.event = event
        self.data = data

    def __str__(self) -> str:
        return f"SSEEvent(event={self.event}, data={self.data})"


class AbstractExecutionEngine(ABC):
    """AI 引擎抽象 - 业务层只依赖这个接口"""

    @abstractmethod
    async def submit(self, task_id: str, goal: str, context: Dict[str, Any]) -> str:
        """异步触发执行，立即返回 execution_id"""

    @abstractmethod
    async def interrupt(self, execution_id: str) -> bool:
        """中断；返回是否成功（用于优雅停止当前节点）"""

    @abstractmethod
    async def resume(self, execution_id: str) -> bool:
        """续跑（从最近 checkpoint 重建状态）"""

    @abstractmethod
    async def get_state(self, execution_id: str) -> Dict[str, Any]:
        """获取执行状态：status / current_node / progress / steps"""

    @abstractmethod
    def stream(self, execution_id: str) -> AsyncIterator[SSEEvent]:
        """订阅任务期间的 SSE 事件流"""


__all__ = ["AbstractExecutionEngine", "SSEEvent"]
