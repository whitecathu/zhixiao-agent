from __future__ import annotations

import asyncio
import inspect
import json
import re
import uuid
from collections.abc import Callable
from typing import Any, ClassVar

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
            if context.permission is not PermissionMode.FULL or not context.approved:
                return ToolResult.blocked(
                    "web search requires approval",
                    root_cause="network access is restricted",
                    retry="approve the network operation and use full permission",
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

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        request = self.validate(arguments)
        if context.permission is not PermissionMode.FULL or not context.approved:
            return ToolResult.blocked(
                "web fetch requires approval",
                root_cause="network access is restricted",
                retry="approve the URL fetch and use full permission",
            )
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                response = await client.get(str(request.url))
                response.raise_for_status()
            content = response.text[: request.max_chars]
            return ToolResult.ok(
                f"fetched {len(content)} characters",
                {
                    "url": str(response.url),
                    "content_type": response.headers.get("content-type"),
                    "content": content,
                },
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
                policy = getattr(context.runner, "policy", None)
                if policy is not None:
                    policy.validate(request.command, context.permission, approved=context.approved)
                job_id = uuid.uuid4().hex
                self._jobs[job_id] = asyncio.create_task(
                    context.runner.run(
                        request.command,
                        permission=context.permission,
                        timeout=request.timeout,
                        approved=context.approved,
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
    description = "Search the workspace's auditable JSONL project-memory index."
    input_model = KnowledgeSearchInput

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        request = self.validate(arguments)
        try:
            path = context.boundary.resolve(request.path)
            if not path.is_file():
                return ToolResult.blocked(
                    "project knowledge index is not initialized",
                    root_cause=str(path),
                    retry="create the JSONL index during knowledge finalization",
                )
            terms = {term.lower() for term in re.findall(r"[\w-]+", request.query)}
            ranked: list[tuple[int, dict[str, Any]]] = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                haystack = json.dumps(item, ensure_ascii=False).lower()
                score = sum(haystack.count(term) for term in terms)
                if score:
                    ranked.append((score, item))
            ranked.sort(key=lambda pair: pair[0], reverse=True)
            return ToolResult.ok(
                f"found {min(len(ranked), request.limit)} knowledge records",
                [item for _, item in ranked[: request.limit]],
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
        if context.permission is not PermissionMode.FULL or not context.approved:
            return ToolResult.blocked(
                "sub-agent delegation requires approval",
                root_cause="full permission was not approved",
                retry="approve the delegation and use full permission",
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
        if context.permission is not PermissionMode.FULL or not context.approved:
            return ToolResult.blocked(
                "MCP invocation requires approval",
                root_cause="full permission was not approved",
                retry="approve the MCP invocation and use full permission",
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


async def _call(handler: Callable[..., Any], *args: Any) -> Any:
    value = handler(*args)
    if inspect.isawaitable(value):
        return await value
    return value
