"""Plugin kernel: contribution registries, inject, and fail-loud composition.

Absorbs DeepSeek Harness's "everything is a plugin" contract without cloning Cordis:

- Plugins describe contributions via ``apply(ctx)``; a tree composes the app.
- Capability seams split Definition / Provider / Consumer. This module owns the
  Definition (``ctx`` keys and vocabularies). Built-in and workspace modules are
  Providers. Runtime, slash, and TUI consume the assembled host and never import
  a provider module.
- Apply errors, missing inject, duplicate names, and escaped plugin paths fail
  loudly. Untrusted workspaces do not load project plugins.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .extensions import HOOK_NAMES, McpServer
from .security import WorkspaceBoundary, WorkspaceViolation
from .settings import AgentSettings, user_config_path
from .tools.base import BaseTool
from .tools.registry import ToolRegistry

PluginSource = Literal["builtin", "user", "workspace"]
CONTRIBUTION_KINDS = ("tools", "commands", "hooks", "skills", "mcp", "prompt", "events")
SEAM_KEYS = ("tools", "commands", "hooks", "skills", "mcp", "prompt")


class PluginError(ValueError):
    """Misconfiguration or apply failure. Loading never skips a broken plugin."""


class PluginApply(Protocol):
    def __call__(self, ctx: PluginContext) -> None: ...


@dataclass(frozen=True)
class CommandContribution:
    name: str
    description: str
    plugin: str
    handler: Callable[[str, Any], Any] | None = None
    template: str | None = None
    mode: str | None = None
    tools: tuple[str, ...] = ()

    def expand(self, arguments: str) -> str:
        if self.template is None:
            raise PluginError(f"command /{self.name} has no run template")
        return self.template.replace("{{args}}", arguments).strip()


@dataclass
class LoadedPlugin:
    name: str
    source: PluginSource
    origin: str
    inject: tuple[str, ...]
    contributions: dict[str, list[str]] = field(
        default_factory=lambda: {kind: [] for kind in CONTRIBUTION_KINDS}
    )


class PluginManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    path: str
    enabled: bool = True
    inject: list[str] = Field(default_factory=list)


class PluginContext:
    """Per-plugin apply surface. Providers register here; they do not import peers."""

    def __init__(self, host: PluginHost, plugin: LoadedPlugin) -> None:
        self.host = host
        self.plugin = plugin

    @property
    def workspace(self) -> Path:
        return self.host.workspace

    @property
    def trusted(self) -> bool:
        return self.host.trusted

    @property
    def settings(self) -> AgentSettings | None:
        return self.host.settings

    @property
    def include_experimental(self) -> bool:
        return self.host.include_experimental

    def provide(self, key: str, service: object) -> None:
        if key in self.host.services:
            raise PluginError(f"service already provided: {key}")
        self.host.services[key] = service

    def get(self, key: str) -> object | None:
        return self.host.services.get(key)

    def require(self, key: str) -> object:
        service = self.get(key)
        if service is None:
            raise PluginError(f"plugin {self.plugin.name} requires missing service: {key}")
        return service

    def register_tool(self, tool: BaseTool) -> None:
        try:
            self.host.tools.register(tool)
        except ValueError as exc:
            raise PluginError(str(exc)) from exc
        self.plugin.contributions["tools"].append(tool.name)

    def register_command(
        self,
        name: str,
        *,
        description: str = "",
        handler: Callable[[str, Any], Any] | None = None,
        template: str | None = None,
        mode: str | None = None,
        tools: tuple[str, ...] = (),
        skip_if_present: bool = False,
    ) -> None:
        key = name.strip().lower()
        if not key:
            raise PluginError("command name cannot be empty")
        if handler is None and template is None:
            raise PluginError(f"command /{key} needs a handler or template")
        if key in self.host.commands:
            if skip_if_present:
                return
            raise PluginError(f"command already registered: /{key}")
        self.host.commands[key] = CommandContribution(
            name=key,
            description=description or key,
            plugin=self.plugin.name,
            handler=handler,
            template=template,
            mode=mode,
            tools=tools,
        )
        self.plugin.contributions["commands"].append(key)

    def register_hook(self, event: str, command: str) -> None:
        if event not in HOOK_NAMES:
            raise PluginError(f"unknown hook name: {event}")
        if not command.strip():
            raise PluginError(f"hook {event} command cannot be empty")
        self.host.hooks.setdefault(event, []).append(command)
        self.plugin.contributions["hooks"].append(event)

    def register_skill_root(self, path: Path) -> None:
        resolved = Path(path).expanduser().resolve()
        if resolved in self.host.skill_roots:
            return
        self.host.skill_roots.append(resolved)
        self.plugin.contributions["skills"].append(str(resolved))

    def register_mcp(self, name: str, server: McpServer) -> None:
        if name in self.host.mcp_servers:
            raise PluginError(f"MCP server already registered: {name}")
        self.host.mcp_servers[name] = server
        self.plugin.contributions["mcp"].append(name)

    def register_prompt_section(self, name: str, text: str) -> None:
        label = name.strip()
        body = text.strip()
        if not label or not body:
            raise PluginError("prompt section requires a name and non-empty text")
        if any(existing == label for existing, _ in self.host.prompt_sections):
            raise PluginError(f"prompt section already registered: {label}")
        self.host.prompt_sections.append((label, body))
        self.plugin.contributions["prompt"].append(label)

    def on(self, event: str, handler: Callable[[Any], None]) -> None:
        if not event.strip():
            raise PluginError("event name cannot be empty")
        self.host.listeners.setdefault(event, []).append(handler)
        self.plugin.contributions["events"].append(event)

    def emit(self, event: str, payload: Any) -> None:
        self.host.emit(event, payload)


class PluginHost:
    """Assembled plugin tree. Consumers read registries; they do not load modules."""

    def __init__(
        self,
        *,
        workspace: Path,
        trusted: bool,
        settings: AgentSettings | None = None,
        include_experimental: bool = False,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.trusted = trusted
        self.settings = settings
        self.include_experimental = include_experimental
        self.tools = ToolRegistry()
        self.commands: dict[str, CommandContribution] = {}
        self.hooks: dict[str, list[str]] = {}
        self.skill_roots: list[Path] = []
        self.mcp_servers: dict[str, McpServer] = {}
        self.prompt_sections: list[tuple[str, str]] = []
        self.services: dict[str, object] = {}
        self.listeners: dict[str, list[Callable[[Any], None]]] = {}
        self.plugins: list[LoadedPlugin] = []

    def emit(self, event: str, payload: Any) -> None:
        for handler in list(self.listeners.get(event, [])):
            handler(payload)

    def render_prompt(self) -> str:
        if not self.prompt_sections:
            return ""
        blocks = [f"### {name}\n{text}" for name, text in self.prompt_sections]
        return "Plugin instructions:\n\n" + "\n\n".join(blocks)

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "workspace": str(self.workspace),
            "trusted": self.trusted,
            "plugins": [
                {
                    "name": plugin.name,
                    "source": plugin.source,
                    "origin": plugin.origin,
                    "inject": list(plugin.inject),
                    "contributions": {
                        kind: names
                        for kind, names in plugin.contributions.items()
                        if names
                    },
                }
                for plugin in self.plugins
            ],
            "seams": {
                "tools": sorted(self.tools.names()),
                "commands": sorted(self.commands),
                "hooks": {name: list(commands) for name, commands in sorted(self.hooks.items())},
                "skills": [str(path) for path in self.skill_roots],
                "mcp": sorted(self.mcp_servers),
                "prompt": [name for name, _ in self.prompt_sections],
            },
        }


@dataclass(frozen=True)
class _PendingPlugin:
    name: str
    source: PluginSource
    origin: str
    inject: tuple[str, ...]
    apply: PluginApply


def load_plugin_tree(
    *,
    workspace: Path,
    trusted: bool,
    settings: AgentSettings | None = None,
    include_experimental: bool = False,
    user_root: Path | None = None,
) -> PluginHost:
    """Load builtins, then explicit user plugins, then trusted workspace plugins."""
    host = PluginHost(
        workspace=workspace,
        trusted=trusted,
        settings=settings,
        include_experimental=include_experimental,
    )
    pending = [
        *_builtin_plugins(),
        *_file_plugins(
            _user_plugin_root(user_root),
            source="user",
            required_inside=None,
        ),
    ]
    if trusted:
        pending.extend(
            _workspace_plugins(host.workspace),
        )
    elif (host.workspace / ".zhixiao" / "plugins.toml").is_file() or (
        host.workspace / ".zhixiao" / "plugins"
    ).is_dir():
        host.emit("plugin/skipped", {"reason": "untrusted_workspace"})
    _apply_tree(host, pending)
    return host


def _user_plugin_root(user_root: Path | None) -> Path:
    if user_root is not None:
        return Path(user_root).expanduser().resolve()
    return user_config_path().expanduser().resolve().parent


def _builtin_plugins() -> list[_PendingPlugin]:
    from . import plugins as builtin_package

    pending: list[_PendingPlugin] = []
    for module_name in builtin_package.BUILTIN_MODULES:
        module = importlib.import_module(module_name)
        pending.append(_module_plugin(module, source="builtin", origin=module_name))
    return pending


def _workspace_plugins(workspace: Path) -> list[_PendingPlugin]:
    root = workspace / ".zhixiao"
    manifest = root / "plugins.toml"
    plugin_dir = root / "plugins"
    if manifest.is_file():
        return _manifest_plugins(
            manifest,
            source="workspace",
            base=workspace,
            required_inside=workspace,
        )
    if plugin_dir.is_dir():
        return _discover_python_plugins(
            plugin_dir,
            source="workspace",
            required_inside=workspace,
        )
    return []


def _file_plugins(
    root: Path,
    *,
    source: PluginSource,
    required_inside: Path | None,
) -> list[_PendingPlugin]:
    manifest = root / "plugins.toml"
    if manifest.is_file():
        return _manifest_plugins(
            manifest,
            source=source,
            base=root,
            required_inside=required_inside or root,
        )
    return []


def _manifest_plugins(
    path: Path,
    *,
    source: PluginSource,
    base: Path,
    required_inside: Path,
) -> list[_PendingPlugin]:
    try:
        with path.open("rb") as handle:
            payload = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise PluginError(f"invalid plugin manifest {path}: {exc}") from exc
    entries = payload.get("plugin", [])
    if not isinstance(entries, list):
        raise PluginError(f"{path} plugin key must be an array of tables")
    pending: list[_PendingPlugin] = []
    for index, item in enumerate(entries):
        if not isinstance(item, Mapping):
            raise PluginError(f"{path} plugin[{index}] must be a table")
        try:
            entry = PluginManifestEntry.model_validate(item)
        except Exception as exc:
            raise PluginError(f"{path} plugin[{index}]: {exc}") from exc
        if not entry.enabled:
            continue
        resolved = _resolve_plugin_path(base, entry.path, required_inside=required_inside)
        module = _load_python_module(resolved, entry.name)
        plugin = _module_plugin(
            module,
            source=source,
            origin=str(resolved),
            name=entry.name,
            inject=tuple(entry.inject) or None,
        )
        pending.append(plugin)
    return pending


def _discover_python_plugins(
    directory: Path,
    *,
    source: PluginSource,
    required_inside: Path,
) -> list[_PendingPlugin]:
    pending: list[_PendingPlugin] = []
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        resolved = _resolve_plugin_path(directory, path.name, required_inside=required_inside)
        module = _load_python_module(resolved, path.stem)
        pending.append(_module_plugin(module, source=source, origin=str(resolved)))
    return pending


def _resolve_plugin_path(base: Path, relative: str, *, required_inside: Path) -> Path:
    candidate = Path(relative)
    target = candidate if candidate.is_absolute() else base / candidate
    try:
        resolved = WorkspaceBoundary(required_inside).resolve(target)
    except (OSError, WorkspaceViolation) as exc:
        raise PluginError(f"plugin path escapes {required_inside}: {relative}") from exc
    if not resolved.is_file():
        raise PluginError(f"plugin module not found: {resolved}")
    if resolved.suffix != ".py":
        raise PluginError(f"plugin module must be a .py file: {resolved}")
    return resolved


def _load_python_module(path: Path, name: str) -> Any:
    module_name = f"zhixiao_plugin_{source_token(name)}_{abs(hash(str(path)))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise PluginError(f"cannot import plugin: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise PluginError(f"plugin {name} failed to import: {exc}") from exc
    return module


def source_token(name: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in name)


def _module_plugin(
    module: Any,
    *,
    source: PluginSource,
    origin: str,
    name: str | None = None,
    inject: tuple[str, ...] | None = None,
) -> _PendingPlugin:
    plugin_name = str(name or getattr(module, "name", None) or Path(origin).stem).strip()
    if not plugin_name:
        raise PluginError(f"plugin at {origin} is missing a name")
    apply = getattr(module, "apply", None)
    if not callable(apply):
        raise PluginError(f"plugin {plugin_name} must export apply(ctx)")
    raw_inject = inject if inject is not None else getattr(module, "inject", ())
    inject_names: tuple[str, ...]
    if isinstance(raw_inject, str):
        inject_names = (raw_inject,)
    else:
        inject_names = tuple(str(item) for item in raw_inject)
    unknown = [item for item in inject_names if item not in SEAM_KEYS]
    if unknown:
        raise PluginError(
            f"plugin {plugin_name} injects unknown seam: {', '.join(unknown)}"
        )
    return _PendingPlugin(
        name=plugin_name,
        source=source,
        origin=origin,
        inject=inject_names,
        apply=apply,
    )


def _apply_tree(host: PluginHost, pending: list[_PendingPlugin]) -> None:
    seen: set[str] = set()
    for plugin in pending:
        if plugin.name in seen:
            raise PluginError(f"duplicate plugin name: {plugin.name}")
        seen.add(plugin.name)
    remaining = list(pending)
    while remaining:
        progress = False
        blocked: list[_PendingPlugin] = []
        for plugin in remaining:
            missing = [key for key in plugin.inject if key not in host.services]
            if missing:
                blocked.append(plugin)
                continue
            record = LoadedPlugin(
                name=plugin.name,
                source=plugin.source,
                origin=plugin.origin,
                inject=plugin.inject,
            )
            context = PluginContext(host, record)
            try:
                plugin.apply(context)
            except PluginError:
                raise
            except Exception as exc:
                raise PluginError(f"plugin {plugin.name} apply failed: {exc}") from exc
            host.plugins.append(record)
            progress = True
        remaining = blocked
        if not progress:
            details = ", ".join(
                f"{plugin.name} needs {', '.join(plugin.inject)}" for plugin in remaining
            )
            raise PluginError(f"unresolved plugin inject: {details}")
