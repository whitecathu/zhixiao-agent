from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..types import ToolResult
from .base import BaseTool, ToolContext
from .filesystem import ExactEditTool, GrepTool, ListDirectoryTool, ReadFileTool, WriteFileTool
from .git import GitDiffTool, GitStatusTool
from .integrations import (
    BackgroundCommandTool,
    KnowledgeSearchTool,
    MCPTool,
    OpenPullRequestTool,
    SubAgentTool,
    WebFetchTool,
    WebSearchTool,
)
from .terminal import TerminalTool, TestTool
from .todo import TodoTool

READ_ONLY_TOOLS = frozenset(
    {
        "list_directory",
        "read_file",
        "grep",
        "git_status",
        "git_diff",
        "knowledge_search",
        "todo",
    }
)


class ToolRegistry:
    def __init__(self, tools: Iterable[BaseTool] = ()):
        self._tools: dict[str, BaseTool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def names(self) -> frozenset[str]:
        """Return the registered tool names without exposing registry internals."""
        return frozenset(self._tools)

    def schemas(self, allowed: set[str] | None = None) -> list[dict[str, Any]]:
        return [
            tool.schema()
            for name, tool in self._tools.items()
            if allowed is None or name in allowed
        ]

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        context: ToolContext,
        *,
        allowed: set[str] | None = None,
    ) -> ToolResult:
        if allowed is not None and name not in allowed:
            return ToolResult.error(
                "tool is not allowed for this agent",
                root_cause=name,
                retry="select a tool from the advertised schema",
            )
        tool = self.get(name)
        if tool is None:
            return ToolResult.error(
                "unknown tool",
                root_cause=name,
                retry="select a registered tool",
            )
        return await tool.execute(arguments, context)


def build_default_registry(*, include_experimental: bool = False) -> ToolRegistry:
    """Build the default tool set.

    MCP and sub_agent stay opt-in until a Worker injects audited adapters.
    """
    tools: list[BaseTool] = [
        ListDirectoryTool(),
        ReadFileTool(),
        GrepTool(),
        ExactEditTool(),
        WriteFileTool(),
        TerminalTool(),
        TestTool(),
        GitStatusTool(),
        GitDiffTool(),
        TodoTool(),
        BackgroundCommandTool(),
        KnowledgeSearchTool(),
        WebSearchTool(),
        WebFetchTool(),
        # Always registered; execute path blocks without FULL + ops_approved.
        OpenPullRequestTool(),
    ]
    if include_experimental:
        tools.extend([SubAgentTool(), MCPTool()])
    return ToolRegistry(tools)