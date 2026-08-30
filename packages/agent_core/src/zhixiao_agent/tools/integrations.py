from __future__ import annotations

import asyncio
import inspect
import ipaddress
import json
import re
import shlex
import socket
import uuid
from collections.abc import Callable
from typing import Any, ClassVar
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import BaseModel, Field, HttpUrl

from ..security import PermissionDenied
from ..types import PermissionMode, ToolResult
from .base import BaseTool, ToolContext


class WebSearchInput(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)


class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the public web after explicit full-permission approval."
    input_model = WebSearchInput

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            request = self.validate(arguments)
            if context.permission is not PermissionMode.FULL or not context.allows_network("web"):
                return ToolResult.blocked(
                    "web search requires approval",
                    root_cause="network access is restricted",
                    retry="approve network_tools and use full permission",
                )
            handler = context.metadata.get("web_search")
            if callable(handler):
                data = await _call(handler, request.query, request.limit)
                return ToolResult.ok("web search completed", data)
            async with httpx.AsyncClient(
                timeout=20,
                follow_redirects=True,
                headers={"User-Agent": "zhixiao-agent/1.0"},
            ) as client:
                response = await client.get(
                    "https://html.duckduckgo.com/html/", params={"q": request.query}
                )
                response.raise_for_status()
            links = re.findall(
                r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                response.text,
                flags=re.IGNORECASE | re.DOTALL,
            )
            results = [
                {"url": url, "title": re.sub(r"<[^>]+>", "", title).strip()}
                for url, title in links[: request.limit]
            ]
            return ToolResult.ok(f"found {len(results)} web results", results)
        except (httpx.HTTPError, ValueError) as exc:
            return ToolResult.error(
                "web search failed",
                root_cause=str(exc),
                retry="check network access or configure a web_search adapter",
            )


class WebFetchInput(BaseModel):
    url: HttpUrl
    max_chars: int = Field(default=50_000, ge=1_000, le=200_000)


class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = "Fetch a public HTTP page with a strict response-size limit."
    input_model = WebFetchInput
    _MAX_REDIRECTS = 5

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        request = self.validate(arguments)
        if context.permission is not PermissionMode.FULL or not context.allows_network("web"):
            return ToolResult.blocked(
                "web fetch requires approval",
                root_cause="network access is restricted",
                retry="approve network_tools and use full permission",
            )
        try:
            current_url = str(request.url)
            async with httpx.AsyncClient(
                timeout=20,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                for redirect_count in range(self._MAX_REDIRECTS + 1):
                    await _validate_public_http_url(current_url)
                    response = await client.get(current_url)
                    if not response.is_redirect:
                        response.raise_for_status()
                        break
                    location = response.headers.get("location")
                    if not location:
                        raise UnsafeWebFetchURL("redirect response is missing a Location header")
                    if redirect_count >= self._MAX_REDIRECTS:
                        raise UnsafeWebFetchURL("web fetch exceeded the redirect limit")
                    current_url = urljoin(str(response.url), location)
            content = response.text[: request.max_chars]
            return ToolResult.ok(
                f"fetched {len(content)} characters",
                {
                    "url": str(response.url),
                    "content_type": response.headers.get("content-type"),
                    "content": content,
                },
            )
        except UnsafeWebFetchURL as exc:
            return ToolResult.blocked(
                "web fetch URL is not allowed",
                root_cause=str(exc),
                retry="use a public HTTP or HTTPS URL without credentials",
            )
        except httpx.HTTPError as exc:
            return ToolResult.error("web fetch failed", root_cause=str(exc), retry="verify the URL")


class BackgroundCommandInput(BaseModel):
    action: str = Field(pattern="^(start|status|terminate)$")
    command: str | None = None
    job_id: str | None = None
    timeout: int = Field(default=600, ge=1, le=3600)


class BackgroundCommandTool(BaseTool):
    name = "background_command"
    description = "Start, inspect, or terminate a policy-checked bounded background command."
    input_model = BackgroundCommandInput
    _jobs: ClassVar[dict[str, asyncio.Task[Any]]] = {}

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        request = self.validate(arguments)
        if request.action == "start":
            if not request.command:
                return ToolResult.error("command is required", root_cause="missing command")
            try:
                # Validate now so rejected jobs never enter the table.
                from ..security import required_command_capability

                capability = required_command_capability(request.command)
                approved = capability is None or context.allows(capability)
                policy = getattr(context.runner, "policy", None)
                if policy is not None:
                    policy.validate(
                        request.command,
                        context.permission,
                        approved=approved,
                    )
                job_id = uuid.uuid4().hex
                self._jobs[job_id] = asyncio.create_task(
                    context.runner.run(
                        request.command,
                        permission=context.permission,
                        timeout=request.timeout,
                        approved=approved,
                    )
                )
                return ToolResult.ok("background command started", {"job_id": job_id})
            except (PermissionDenied, OSError, ValueError) as exc:
                return ToolResult.error("background command rejected", root_cause=str(exc))
        if not request.job_id or request.job_id not in self._jobs:
            return ToolResult.error(
                "background job not found", root_cause=request.job_id or "missing job_id"
            )
        task = self._jobs[request.job_id]
        if request.action == "terminate":
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            self._jobs.pop(request.job_id, None)
            return ToolResult.ok("background command terminated", {"job_id": request.job_id})
        if not task.done():
            return ToolResult.ok(
                "background command is running", {"job_id": request.job_id, "state": "running"}
            )
        self._jobs.pop(request.job_id, None)
        try:
            result = task.result()
        except Exception as exc:  # command adapters can fail independently
            return ToolResult.error("background command failed", root_cause=str(exc))
        status = "succeeded" if result.exit_code == 0 else "failed"
        return ToolResult.ok(
            f"background command {status}",
            {"job_id": request.job_id, **result.model_dump()},
        )


class KnowledgeSearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    path: str = ".zhixiao/knowledge.jsonl"
    limit: int = Field(default=5, ge=1, le=50)


class KnowledgeSearchTool(BaseTool):
    name = "knowledge_search"
    description = (
        "Search workspace semantic/keyword index when present, else the auditable "
        "JSONL project-memory knowledge file."
    )
    input_model = KnowledgeSearchInput

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        request = self.validate(arguments)
        try:
            from ..rag.workspace_index import index_exists, search_workspace

            if index_exists(context.workspace):
                index_hits = await search_workspace(
                    context.workspace, request.query, limit=request.limit
                )
                if index_hits:
                    hits = [
                        {
                            "source_path": hit.path,
                            "score": hit.score,
                            "citation": hit.chunk_id or hit.path,
                            "record": hit.as_dict(),
                        }
                        for hit in index_hits
                    ]
                    return ToolResult.ok(
                        f"found {len(hits)} workspace index hits with evidence citations",
                        {
                            "hits": hits,
                            "evidence_required": True,
                            "degraded": False,
                            "channel": "workspace_index",
                        },
                    )
                # Empty index results degrade to knowledge.jsonl when available.

            path = context.boundary.resolve(request.path)
            if not path.is_file():
                if index_exists(context.workspace):
                    return ToolResult.ok(
                        "no workspace index evidence found; answers must degrade without citations",
                        {
                            "hits": [],
                            "evidence_required": True,
                            "degraded": True,
                            "channel": "workspace_index",
                        },
                    )
                return ToolResult.blocked(
                    "project knowledge index is not initialized",
                    root_cause=str(path),
                    retry=(
                        "create the JSONL index during knowledge finalization "
                        "or run index_workspace"
                    ),
                )
            terms = {term.lower() for term in re.findall(r"[\w-]+", request.query)}

            def _scan() -> list[dict[str, Any]]:
                ranked: list[tuple[int, dict[str, Any]]] = []
                with path.open(encoding="utf-8") as handle:
                    for line in handle:
                        if not line.strip():
                            continue
                        item = json.loads(line)
                        haystack = json.dumps(item, ensure_ascii=False).lower()
                        score = sum(haystack.count(term) for term in terms)
                        if score:
                            ranked.append((score, item))
                ranked.sort(key=lambda pair: pair[0], reverse=True)
                hits = []
                for score, item in ranked[: request.limit]:
                    evidence = {
                        "source_path": str(path),
                        "score": score,
                        "citation": item.get("id") or item.get("title") or item.get("summary"),
                        "record": item,
                    }
                    hits.append(evidence)
                return hits

            hits = await asyncio.to_thread(_scan)
            if not hits:
                return ToolResult.ok(
                    "no knowledge evidence found; answers must degrade without citations",
                    {
                        "hits": [],
                        "evidence_required": True,
                        "degraded": True,
                        "channel": "knowledge_jsonl",
                    },
                )
            return ToolResult.ok(
                f"found {len(hits)} knowledge records with evidence citations",
                {
                    "hits": hits,
                    "evidence_required": True,
                    "degraded": False,
                    "channel": "knowledge_jsonl",
                },
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return ToolResult.error("knowledge search failed", root_cause=str(exc))

class DelegateInput(BaseModel):
    task: str = Field(min_length=5, max_length=10_000)


class SubAgentTool(BaseTool):
    name = "sub_agent"
    description = "Delegate one bounded task through the configured sub-agent adapter."
    input_model = DelegateInput

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        request = self.validate(arguments)
        if context.permission is not PermissionMode.FULL or not context.allows("sub_agent"):
            return ToolResult.blocked(
                "sub-agent delegation requires approval",
                root_cause="high-risk ops were not approved",
                retry="approve the sub_agent operation and use full permission",
            )
        handler = context.metadata.get("sub_agent")
        if not callable(handler):
            return ToolResult.blocked(
                "sub-agent adapter is not configured",
                root_cause="missing metadata.sub_agent callback",
                retry="configure an audited sub-agent callback",
            )
        try:
            return ToolResult.ok("sub-agent completed", await _call(handler, request.task))
        except Exception as exc:
            return ToolResult.error("sub-agent failed", root_cause=str(exc))


class MCPInput(BaseModel):
    server: str = Field(min_length=1, max_length=128)
    tool: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)


class MCPTool(BaseTool):
    name = "mcp"
    description = "Invoke a whitelisted MCP server through the configured adapter."
    input_model = MCPInput

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        request = self.validate(arguments)
        if context.permission is not PermissionMode.FULL or not context.allows("mcp"):
            return ToolResult.blocked(
                "MCP invocation requires approval",
                root_cause="high-risk ops were not approved",
                retry="approve the MCP invocation and use full permission",
            )
        transports = context.metadata.get("mcp_server_transports") or {}
        transport = transports.get(request.server) if isinstance(transports, dict) else None
        network_flag = context.metadata.get("mcp_network_approved")
        if network_flag is False and transport != "stdio":
            return ToolResult.blocked(
                "MCP HTTP transport requires network approval",
                root_cause="mcp network capability was not granted",
                retry="approve mcp network access or use local MCP handlers",
            )
        handler = context.metadata.get("mcp")
        whitelist = set(context.metadata.get("mcp_whitelist", []))
        target = f"{request.server}:{request.tool}"
        if target not in whitelist:
            return ToolResult.blocked(
                "MCP operation is not whitelisted",
                root_cause=target,
                retry="add the exact server:tool pair to the run whitelist",
            )
        if not callable(handler):
            return ToolResult.blocked(
                "MCP adapter is not configured",
                root_cause="missing metadata.mcp callback",
                retry="configure an audited MCP callback",
            )
        try:
            return ToolResult.ok(
                "MCP tool completed",
                await _call(handler, request.server, request.tool, request.arguments),
            )
        except Exception as exc:
            return ToolResult.error("MCP tool failed", root_cause=str(exc))


class OpenPullRequestInput(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(default="", max_length=20_000)
    base: str = Field(default="main", min_length=1, max_length=128)
    head: str | None = Field(default=None, max_length=128)
    draft: bool = False


class OpenPullRequestTool(BaseTool):
    """Open a pull request via metadata callback or ``gh pr create``.

    Requires PermissionMode.FULL and an explicit ``git_publish`` capability.
    Network-backed ``gh`` additionally requires the ``git_publish`` network
    capability. TaskExec can request a dedicated ``git_publish`` approval which
    re-enqueues a publish follow-up job.
    """

    name = "open_pull_request"
    description = (
        "Open a GitHub pull request after explicit full-permission and ops approval."
    )
    input_model = OpenPullRequestInput

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        request = self.validate(arguments)
        if context.permission is not PermissionMode.FULL:
            return ToolResult.blocked(
                "opening a pull request requires full permission",
                root_cause="full permission was not granted",
                retry="use full permission and explicitly approve git publication",
            )
        publish_approved = _git_publish_approved(context)
        if not publish_approved:
            return ToolResult.blocked(
                "opening a pull request requires git publish approval",
                root_cause="metadata does not grant the git_publish capability",
                retry=(
                    "set metadata.publish_approved=true or include git_publish "
                    "in metadata.ops_capabilities"
                ),
            )
        handler = context.metadata.get("open_pr")
        if callable(handler):
            try:
                data = await _call(
                    handler,
                    request.title,
                    request.body,
                    request.base,
                    request.head,
                    request.draft,
                )
                return ToolResult.ok("pull request opened", data)
            except Exception as exc:
                return ToolResult.error("open pull request failed", root_cause=str(exc))

        if not context.allows_network("git_publish"):
            return ToolResult.blocked(
                "opening a pull request via gh requires network approval",
                root_cause="network access is restricted",
                retry="approve git_publish network access or configure metadata.open_pr",
            )
        try:
            command = [
                "gh",
                "pr",
                "create",
                "--title",
                request.title,
                "--body",
                request.body or request.title,
                "--base",
                request.base,
            ]
            if request.head:
                command.extend(["--head", request.head])
            if request.draft:
                command.append("--draft")
            # Prefer shlex.join so LocalRunner's shlex.split rebuilds argv safely.
            quoted = shlex.join(command)
            result = await context.runner.run(
                quoted,
                permission=PermissionMode.FULL,
                approved=publish_approved,
            )
            if result.exit_code != 0:
                return ToolResult.error(
                    "gh pr create failed",
                    root_cause=result.stderr or result.stdout or f"exit {result.exit_code}",
                    retry="ensure gh is authenticated and the branch is pushed",
                )
            return ToolResult.ok(
                "pull request opened via gh",
                {"stdout": result.stdout, "stderr": result.stderr},
            )
        except (PermissionDenied, OSError, ValueError) as exc:
            return ToolResult.error("open pull request failed", root_cause=str(exc))


async def _call(handler: Callable[..., Any], *args: Any) -> Any:
    value = handler(*args)
    if inspect.isawaitable(value):
        return await value
    return value


class UnsafeWebFetchURL(ValueError):
    """Raised when a URL or one of its resolved addresses is not public."""


async def _validate_public_http_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeWebFetchURL(f"invalid URL: {exc}") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafeWebFetchURL("only HTTP and HTTPS URLs are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeWebFetchURL("URL user information is not allowed")
    host = parsed.hostname
    if not host:
        raise UnsafeWebFetchURL("URL must include a hostname")
    effective_port = port or (443 if parsed.scheme.lower() == "https" else 80)
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        try:
            addresses = await asyncio.to_thread(_resolve_host_addresses, host, effective_port)
        except OSError as exc:
            raise UnsafeWebFetchURL(f"hostname resolution failed for {host}: {exc}") from exc
        if not addresses:
            raise UnsafeWebFetchURL(
                f"hostname resolution returned no addresses for {host}"
            ) from None
    else:
        addresses = {str(literal)}
    for address in addresses:
        try:
            resolved = ipaddress.ip_address(address)
        except ValueError as exc:
            raise UnsafeWebFetchURL(f"hostname resolved to an invalid address: {address}") from exc
        if any(
            (
                resolved.is_loopback,
                resolved.is_link_local,
                resolved.is_private,
                resolved.is_multicast,
                resolved.is_reserved,
                resolved.is_unspecified,
            )
        ):
            raise UnsafeWebFetchURL(
                f"hostname {host} resolves to a non-public address: {resolved}"
            )


def _resolve_host_addresses(host: str, port: int) -> set[str]:
    return {
        str(sockaddr[0])
        for _family, _type, _proto, _canonname, sockaddr in socket.getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
        )
    }


def _git_publish_approved(context: ToolContext) -> bool:
    if context.allows("git_publish"):
        return True
    metadata = context.metadata
    if metadata.get("publish_approved") is True:
        return True
    capabilities = metadata.get("ops_capabilities")
    return isinstance(capabilities, (list, tuple, set, frozenset, dict)) and (
        "git_publish" in capabilities
    )
