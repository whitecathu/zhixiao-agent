from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from ..runner import Runner
from ..security import WorkspaceBoundary
from ..types import PermissionMode, ToolResult


class EmptyInput(BaseModel):
    pass


class ToolContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    workspace: Path
    permission: PermissionMode
    runner: Runner
    # Plan/run-start gate: allows edit/execute after human start approval.
    approved: bool = False
    # Separate high-risk ops (destructive commands, publish, MCP, sub-agent).
    ops_approved: bool = False
    # Operation-scoped approvals. The legacy boolean never grants a capability by itself.
    ops_capabilities: frozenset[str] = Field(default_factory=frozenset)
    # Separate network approval for web_search / web_fetch / remote clone.
    network_approved: bool = False
    network_capabilities: frozenset[str] = Field(default_factory=frozenset)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def boundary(self) -> WorkspaceBoundary:
        return WorkspaceBoundary(self.workspace)

    def allows(self, capability: str) -> bool:
        return capability in self.ops_capabilities

    def allows_network(self, capability: str) -> bool:
        return capability in self.network_capabilities


class BaseTool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    input_model: ClassVar[type[BaseModel]] = EmptyInput

    @abstractmethod
    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult: ...

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_model.model_json_schema(),
            },
        }

    def validate(self, arguments: dict[str, Any]) -> Any:
        return self.input_model.model_validate(arguments)
