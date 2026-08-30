"""File-format Providers for workspace commands, hooks, and extra skill roots.

Trusted ``.zhixiao/commands``, ``hooks.toml``, and ``skills`` are not a parallel
extension system: they contribute to the same seams Python plugins use.
"""

from __future__ import annotations

from ..extensions import load_custom_commands, load_hooks
from ..plugin import PluginContext

name = "workspace.extensions"
inject = ("commands", "skills")


def apply(ctx: PluginContext) -> None:
    if not ctx.trusted:
        ctx.provide("hooks", ctx.host.hooks)
        return
    for command in load_custom_commands(ctx.workspace, trusted=True).values():
        ctx.register_command(
            command.name,
            description=command.description,
            template=command.template,
            mode=command.mode,
            tools=command.tools,
            skip_if_present=True,
        )
    for event, commands in load_hooks(ctx.workspace, trusted=True).items():
        for hook_command in commands:
            ctx.register_hook(event, hook_command)
    ctx.provide("hooks", ctx.host.hooks)
