"""Service Provider for the MCP seam: local no-secret server definitions."""

from __future__ import annotations

from ..extensions import McpConfigStore
from ..plugin import PluginContext

name = "core.mcp"
inject: tuple[str, ...] = ()


def apply(ctx: PluginContext) -> None:
    if ctx.settings is not None:
        for server_name, server in McpConfigStore(ctx.settings.state_dir).load().items():
            ctx.register_mcp(server_name, server)
    ctx.provide("mcp", ctx.host.mcp_servers)
