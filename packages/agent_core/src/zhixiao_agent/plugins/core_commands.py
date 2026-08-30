"""Service Provider for the commands seam: built-in human slash commands."""

from __future__ import annotations

from ..plugin import PluginContext
from ..slash import builtin_command_handlers

name = "core.commands"
inject: tuple[str, ...] = ()


def apply(ctx: PluginContext) -> None:
    for command_name, handler in builtin_command_handlers().items():
        ctx.register_command(command_name, description=command_name, handler=handler)
    ctx.provide("commands", ctx.host.commands)
