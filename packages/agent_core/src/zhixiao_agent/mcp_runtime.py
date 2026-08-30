from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from .extensions import McpServer


class LocalMcpRuntime:
    def __init__(
        self,
        servers: dict[str, McpServer],
        *,
        workspace: Path,
        network_approved: bool,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.servers = servers
        self.workspace = workspace.resolve()
        self.network_approved = network_approved
        self.http_transport = http_transport

    @property
    def whitelist(self) -> list[str]:
        return sorted(
            f"{server}:{tool}"
            for server, definition in self.servers.items()
            for tool in definition.tool_allowlist
        )

    async def __call__(self, server: str, tool: str, arguments: dict[str, Any]) -> Any:
        definition = self.servers.get(server)
        if definition is None:
            raise PermissionError(f"MCP server is not configured: {server}")
        if tool not in definition.tool_allowlist:
            raise PermissionError(f"MCP operation is not whitelisted: {server}:{tool}")
        if definition.transport == "stdio":
            return await self._stdio(definition, tool, arguments)
        if not self.network_approved:
            raise PermissionError("MCP HTTP transport requires network approval")
        return await self._http(definition, tool, arguments)

    async def _stdio(self, definition: McpServer, tool: str, arguments: dict[str, Any]) -> Any:
        if not definition.command:
            raise RuntimeError("stdio MCP server has no command")
        env = {key: value for key, value in os.environ.items() if key.upper() in _SAFE_MCP_ENV}
        for target, reference in definition.env.items():
            if reference not in os.environ:
                raise RuntimeError(f"missing MCP credential environment variable: {reference}")
            env[target] = os.environ[reference]
        process = await asyncio.create_subprocess_exec(
            definition.command,
            *definition.args,
            cwd=self.workspace,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(json.dumps(request).encode("utf-8") + b"\n"),
                timeout=definition.call_timeout,
            )
        except TimeoutError:
            process.kill()
            await process.communicate()
            raise TimeoutError(
                f"MCP stdio call timed out after {definition.call_timeout}s"
            ) from None
        if process.returncode != 0:
            raise RuntimeError(stderr.decode(errors="replace")[-2_000:] or "MCP server failed")
        try:
            response = json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"MCP server returned invalid JSON: {exc}") from exc
        if isinstance(response, dict) and response.get("error"):
            raise RuntimeError(f"MCP server returned error: {response['error']}")
        return response.get("result") if isinstance(response, dict) else response

    async def _http(self, definition: McpServer, tool: str, arguments: dict[str, Any]) -> Any:
        if not definition.url:
            raise RuntimeError("HTTP MCP server has no URL")
        parsed = urlsplit(definition.url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise RuntimeError("HTTP MCP URL must use http(s) and include a host")
        if parsed.username or parsed.password:
            raise RuntimeError("HTTP MCP URL must not contain credentials")
        headers = {"content-type": "application/json", "accept": "application/json"}
        for target, reference in definition.env.items():
            if reference not in os.environ:
                raise RuntimeError(f"missing MCP credential environment variable: {reference}")
            headers[target] = os.environ[reference]
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        async with httpx.AsyncClient(
            timeout=definition.call_timeout,
            transport=self.http_transport,
        ) as client:
            response = await client.post(definition.url, json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()
        if isinstance(body, dict) and body.get("error"):
            raise RuntimeError(f"MCP server returned error: {body['error']}")
        return body.get("result") if isinstance(body, dict) else body


_SAFE_MCP_ENV = {
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "PYTHONIOENCODING",
    "VIRTUAL_ENV",
}


def mcp_metadata(
    servers: dict[str, McpServer],
    *,
    workspace: Path,
    network_approved: bool,
) -> dict[str, Any]:
    runtime = LocalMcpRuntime(
        servers,
        workspace=workspace,
        network_approved=network_approved,
    )
    return {
        "mcp": runtime,
        "mcp_whitelist": runtime.whitelist,
        "mcp_network_approved": network_approved,
        "mcp_server_transports": {name: server.transport for name, server in servers.items()},
    }
