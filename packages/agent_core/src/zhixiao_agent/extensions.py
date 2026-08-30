from __future__ import annotations

import json
import os
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


class McpServer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transport: Literal["stdio", "http"]
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    tool_allowlist: list[str] = Field(default_factory=list)
    startup_timeout: int = Field(default=15, ge=1, le=300)
    call_timeout: int = Field(default=60, ge=1, le=600)

    @field_validator("env")
    @classmethod
    def env_references_only(cls, value: dict[str, str]) -> dict[str, str]:
        for variable, reference in value.items():
            if not variable or not reference or reference != reference.upper():
                raise ValueError("MCP env values must be environment variable names")
        return value

    def diagnose(self) -> tuple[bool, str]:
        missing = [reference for reference in self.env.values() if reference not in os.environ]
        if missing:
            return False, f"missing environment variables: {', '.join(sorted(missing))}"
        if self.transport == "stdio":
            if not self.command:
                return False, "stdio transport requires command"
            if shutil.which(self.command) is None and not Path(self.command).is_file():
                return False, f"executable not found: {self.command}"
            return True, "stdio server configuration is ready"
        if not self.url or urlparse(self.url).scheme not in {"http", "https"}:
            return False, "http transport requires an http(s) URL"
        return True, "HTTP server configuration is valid; connectivity was not attempted"


class McpConfigStore:
    def __init__(self, state_dir: Path):
        self.path = state_dir.expanduser().resolve() / "mcp.json"

    def load(self) -> dict[str, McpServer]:
        if not self.path.is_file():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        servers = payload.get("servers", {}) if isinstance(payload, dict) else {}
        return {name: McpServer.model_validate(item) for name, item in servers.items()}

    def save(self, servers: dict[str, McpServer]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": "1", "servers": {}}
        payload["servers"] = {
            name: server.model_dump(mode="json", exclude_none=True)
            for name, server in sorted(servers.items())
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, name: str, server: McpServer) -> None:
        servers = self.load()
        servers[name] = server
        self.save(servers)

    def remove(self, name: str) -> bool:
        servers = self.load()
        if name not in servers:
            return False
        del servers[name]
        self.save(servers)
        return True


@dataclass(frozen=True)
class CustomCommand:
    name: str
    description: str
    mode: str
    tools: tuple[str, ...]
    template: str
    path: Path

    def expand(self, arguments: str) -> str:
        return self.template.replace("{{args}}", arguments).strip()


def load_custom_commands(workspace: Path, *, trusted: bool) -> dict[str, CustomCommand]:
    if not trusted:
        return {}
    root = workspace / ".zhixiao" / "commands"
    if not root.is_dir():
        return {}
    commands: dict[str, CustomCommand] = {}
    for path in root.glob("*.md"):
        metadata, body = _frontmatter(path)
        name = str(metadata.get("name", path.stem)).strip()
        tools = tuple(part.strip() for part in str(metadata.get("tools", "")).split(",") if part)
        commands[name] = CustomCommand(
            name=name,
            description=str(metadata.get("description", "")),
            mode=str(metadata.get("mode", "ask")),
            tools=tools,
            template=body,
            path=path,
        )
    return commands


def expand_custom_command(prompt: str, workspace: Path, *, trusted: bool) -> str:
    if not prompt.startswith("/"):
        return prompt
    invocation, _, arguments = prompt[1:].partition(" ")
    command = load_custom_commands(workspace, trusted=trusted).get(invocation)
    return command.expand(arguments) if command else prompt


def _frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) != 3:
        raise ValueError(f"invalid frontmatter: {path}")
    metadata: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip()
    return metadata, parts[2].strip()


HOOK_NAMES = {"before_run", "before_tool", "after_tool", "after_verification", "after_run"}


def load_hooks(workspace: Path, *, trusted: bool) -> dict[str, list[str]]:
    if not trusted:
        return {}
    path = workspace / ".zhixiao" / "hooks.toml"
    if not path.is_file():
        return {}
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    hooks = payload.get("hooks", {})
    unknown = set(hooks) - HOOK_NAMES
    if unknown:
        raise ValueError(f"unknown hook names: {', '.join(sorted(unknown))}")
    result: dict[str, list[str]] = {}
    for name, commands in hooks.items():
        if isinstance(commands, str):
            result[name] = [commands]
        elif isinstance(commands, list) and all(isinstance(item, str) for item in commands):
            result[name] = commands
        else:
            raise ValueError(f"hook {name} must be a string or array of strings")
    return result
