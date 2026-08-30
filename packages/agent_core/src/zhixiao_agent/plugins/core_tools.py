"""Service Provider for the tools seam: the default typed tool registry."""

from __future__ import annotations

from ..plugin import PluginContext
from ..tools.registry import build_default_registry

name = "core.tools"
inject: tuple[str, ...] = ()


def apply(ctx: PluginContext) -> None:
    registry = build_default_registry(include_experimental=ctx.include_experimental)
    for tool_name in sorted(registry.names()):
        tool = registry.get(tool_name)
        if tool is not None:
            ctx.register_tool(tool)
    ctx.provide("tools", ctx.host.tools)
