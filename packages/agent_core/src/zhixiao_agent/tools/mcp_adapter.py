from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

import httpx

MCPHandler = Callable[[str, str, dict[str, Any]], Any]
MCPCallableMap = dict[str, Callable[..., Any]]
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9.-]+$")


@dataclass(frozen=True)
class MCPAdapterConfig:
    """Audited MCP callback configuration for Worker / Runtime metadata."""

    whitelist: list[str] = field(default_factory=list)
    http_base: str | None = None
    allowed_hosts: list[str] = field(default_factory=list)
    # Keys are exact "server:tool" pairs; values are sync/async callables.
    callables: MCPCallableMap = field(default_factory=dict)
    timeout: float = 30.0
    enabled: bool = False

    def is_configured(self) -> bool:
        return bool(self.whitelist or self.http_base or self.callables or self.enabled)


def parse_mcp_whitelist(env_value: str) -> list[str]:
    """Parse comma-separated ``server:tool`` pairs from ``MCP_WHITELIST``."""
    if not env_value or not env_value.strip():
        return []
    targets = [part.strip() for part in env_value.split(",") if part.strip()]
    for target in targets:
        _validate_target(target)
    return targets


def load_mcp_adapter_config(environ: Mapping[str, str] | None = None) -> MCPAdapterConfig:
    """Load structured MCP adapter config from ``MCP_*`` environment variables."""
    env = os.environ if environ is None else environ
    whitelist = parse_mcp_whitelist(env.get("MCP_WHITELIST", ""))
    allowed_hosts = _parse_allowed_hosts(env.get("MCP_ALLOWED_HOSTS", ""))
    http_base = _validate_http_base(
        (env.get("MCP_HTTP_BASE") or "").strip().rstrip("/") or None,
        allowed_hosts,
    )
    enabled = (env.get("MCP_ENABLED") or "").lower() in {"1", "true", "yes"}
    servers_raw = (env.get("MCP_SERVERS") or "").strip()
    if servers_raw:
        try:
            payload = json.loads(servers_raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"MCP_SERVERS must be valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("MCP_SERVERS must be a JSON object")
        for server in payload:
            _validate_identifier(str(server), label="server")
    callables: MCPCallableMap = {}
    local_raw = (env.get("MCP_LOCAL_HANDLERS") or "").strip()
    if local_raw:
        try:
            local_payload = json.loads(local_raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"MCP_LOCAL_HANDLERS must be valid JSON: {exc}") from exc
        if not isinstance(local_payload, dict):
            raise ValueError("MCP_LOCAL_HANDLERS must be a JSON object")
        for key, value in local_payload.items():
            target = str(key)
            _validate_target(target)
            callables[target] = (lambda arguments, _value=value: _value)
    return MCPAdapterConfig(
        whitelist=whitelist,
        http_base=http_base,
        allowed_hosts=allowed_hosts,
        callables=callables,
        enabled=enabled,
    )


def mcp_config_from_env(environ: Mapping[str, str] | None = None) -> dict[str, Any] | None:
    """Return Runtime ``tool_metadata`` fragment when MCP is configured."""
    config = load_mcp_adapter_config(environ)
    if not config.is_configured():
        return None
    return {
        "mcp": build_mcp_handler(config),
        "mcp_whitelist": list(config.whitelist),
    }


def build_mcp_handler(
    config: MCPAdapterConfig | Mapping[str, Any] | None = None,
) -> MCPHandler:
    """Return an audited MCP callback for ``metadata['mcp']``.

    v1 transports:
    - in-process: invoke a registered callable for ``server:tool``
    - HTTP: ``POST {http_base}/mcp/{server}/{tool}`` with JSON arguments

    Failures raise so ``MCPTool`` wraps them as ``ToolResult.error``.
    """
    resolved = _normalize_config(config)

    def handler(server: str, tool: str, arguments: dict[str, Any]) -> Any:
        _validate_identifier(server, label="server")
        _validate_identifier(tool, label="tool")
        target = f"{server}:{tool}"
        if target not in resolved.whitelist:
            raise PermissionError(f"MCP operation is not whitelisted: {target}")
        registered = resolved.callables.get(target)
        if registered is not None:
            return registered(arguments)
        if resolved.http_base:
            return _http_invoke(resolved.http_base, server, tool, arguments, resolved.timeout)
        raise RuntimeError(
            f"no MCP transport configured for {target}; "
            "register an in-process callable or set MCP_HTTP_BASE"
        )

    return handler


def _normalize_config(
    config: MCPAdapterConfig | Mapping[str, Any] | None,
) -> MCPAdapterConfig:
    if config is None:
        return MCPAdapterConfig()
    if isinstance(config, MCPAdapterConfig):
        callables = dict(config.callables)
        http_base = config.http_base
        whitelist = list(config.whitelist)
        allowed_hosts = list(config.allowed_hosts)
        timeout = config.timeout
        enabled = config.enabled
    else:
        callables = dict(config.get("callables") or {})
        http_base = config.get("http_base")
        whitelist = list(config.get("whitelist") or [])
        allowed_hosts = list(config.get("allowed_hosts") or [])
        timeout = float(config.get("timeout") or 30.0)
        enabled = bool(config.get("enabled", False))
    for target in whitelist:
        _validate_target(str(target))
    for target in callables:
        _validate_target(str(target))
    normalized_hosts = [_normalize_allowed_host(str(host)) for host in allowed_hosts]
    if isinstance(http_base, str):
        http_base = http_base.strip().rstrip("/") or None
    http_base = _validate_http_base(http_base, normalized_hosts)
    return MCPAdapterConfig(
        whitelist=[str(target) for target in whitelist],
        http_base=http_base,
        allowed_hosts=normalized_hosts,
        callables=callables,
        timeout=timeout,
        enabled=enabled,
    )


def _validate_identifier(value: str, *, label: str) -> str:
    if (
        not value
        or not _IDENTIFIER_RE.fullmatch(value)
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or "%" in value
    ):
        raise ValueError(
            f"invalid MCP {label} identifier {value!r}; "
            "use only letters, digits, '.', '_', and '-'"
        )
    return value


def _validate_target(target: str) -> tuple[str, str]:
    if target.count(":") != 1:
        raise ValueError(f"invalid MCP whitelist target {target!r}; expected server:tool")
    server, tool = target.split(":", 1)
    return (
        _validate_identifier(server, label="server"),
        _validate_identifier(tool, label="tool"),
    )


def _parse_allowed_hosts(value: str) -> list[str]:
    if not value or not value.strip():
        return []
    return [
        _normalize_allowed_host(host)
        for host in value.split(",")
        if host.strip()
    ]


def _normalize_allowed_host(value: str) -> str:
    host = value.strip().lower().rstrip(".")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if not host or any(character in host for character in "/\\%@"):
        raise ValueError(f"invalid MCP allowed host {value!r}")
    try:
        return str(ip_address(host))
    except ValueError:
        if not _HOSTNAME_RE.fullmatch(host) or ".." in host:
            raise ValueError(f"invalid MCP allowed host {value!r}") from None
        return host


def _validate_http_base(http_base: str | None, allowed_hosts: list[str]) -> str | None:
    if http_base is None:
        return None
    parsed = urlsplit(http_base)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("MCP_HTTP_BASE must use http or https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("MCP_HTTP_BASE must not contain user information")
    if not parsed.hostname:
        raise ValueError("MCP_HTTP_BASE must include a host")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(f"MCP_HTTP_BASE has an invalid port: {exc}") from exc
    if parsed.query or parsed.fragment:
        raise ValueError("MCP_HTTP_BASE must not contain a query or fragment")
    host = _normalize_allowed_host(parsed.hostname)
    if not allowed_hosts:
        raise ValueError("MCP_ALLOWED_HOSTS must explicitly allow the MCP_HTTP_BASE host")
    if host not in allowed_hosts:
        raise ValueError(f"MCP_HTTP_BASE host {host!r} is not in MCP_ALLOWED_HOSTS")
    if parsed.scheme != "https" and host not in {"localhost", "127.0.0.1"}:
        raise ValueError("MCP_HTTP_BASE requires https except for localhost or 127.0.0.1")
    return http_base


def _http_invoke(
    http_base: str,
    server: str,
    tool: str,
    arguments: dict[str, Any],
    timeout: float,
) -> Any:
    url = f"{http_base}/mcp/{server}/{tool}"
    response = httpx.post(url, json=arguments, timeout=timeout)
    response.raise_for_status()
    if not response.content:
        return {"status": "ok"}
    try:
        return response.json()
    except json.JSONDecodeError:
        return {"raw": response.text}
