"""Service Provider for the skills seam: package and trusted workspace roots."""

from __future__ import annotations

from ..plugin import PluginContext
from ..skills import default_skill_roots

name = "core.skills"
inject: tuple[str, ...] = ()


def apply(ctx: PluginContext) -> None:
    for root in default_skill_roots(ctx.workspace, trusted_workspace=ctx.trusted):
        ctx.register_skill_root(root)
    ctx.provide("skills", ctx.host.skill_roots)
