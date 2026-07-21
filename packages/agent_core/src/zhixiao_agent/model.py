from __future__ import annotations

import asyncio
import json
import time
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from .types import ModelTurn, ToolCall


class CodingModel(ABC):
    @abstractmethod
    async def complete(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelTurn: ...


@dataclass(frozen=True)
class ModelProfile:
    provider: str
    model: str
    api_base: str
    api_key: str
    timeout: float = 120.0
    requests_per_minute: int = 60
    max_concurrency: int = 4
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0


@dataclass
class ModelUsage:
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


class OpenAICompatibleModel(CodingModel):
    def __init__(self, profile: ModelProfile, *, client: httpx.AsyncClient | None = None):
        self.profile = profile
        self.client = client or httpx.AsyncClient(timeout=profile.timeout)
        self.usage = ModelUsage()
        self._semaphore = asyncio.Semaphore(profile.max_concurrency)
        self._request_times: deque[float] = deque()
        self._rate_lock = asyncio.Lock()

    async def _throttle(self) -> None:
        async with self._rate_lock:
            now = time.monotonic()
            while self._request_times and now - self._request_times[0] >= 60:
                self._request_times.popleft()
            if len(self._request_times) >= self.profile.requests_per_minute:
                delay = 60 - (now - self._request_times[0])
                await asyncio.sleep(max(delay, 0))
            self._request_times.append(time.monotonic())

    async def complete(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelTurn:
        payload: dict[str, Any] = {
            "model": self.profile.model,
            "messages": list(messages),
            "temperature": 0,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        async with self._semaphore:
            await self._throttle()
            response = await self.client.post(
                f"{self.profile.api_base.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.profile.api_key}"},
                json=payload,
            )
        response.raise_for_status()
        body = response.json()
        message = body["choices"][0]["message"]
        calls = []
        for raw in message.get("tool_calls", []):
            function = raw["function"]
            arguments = function.get("arguments") or "{}"
            calls.append(
                ToolCall(
                    id=raw.get("id", function["name"]),
                    name=function["name"],
                    arguments=json.loads(arguments) if isinstance(arguments, str) else arguments,
                )
            )
        usage = body.get("usage", {})
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        cost = (
            prompt_tokens * self.profile.input_cost_per_million
            + completion_tokens * self.profile.output_cost_per_million
        ) / 1_000_000
        self.usage.requests += 1
        self.usage.prompt_tokens += prompt_tokens
        self.usage.completion_tokens += completion_tokens
        self.usage.cost_usd += cost
        return ModelTurn(
            content=message.get("content") or "",
            tool_calls=calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=body.get("model", self.profile.model),
            cost_usd=cost,
        )


class FallbackModel(CodingModel):
    """Use the fallback only for transport, rate-limit, or invalid-response failures."""

    def __init__(self, primary: CodingModel, fallback: CodingModel):
        self.primary = primary
        self.fallback = fallback
        self.fallback_count = 0

    async def complete(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelTurn:
        try:
            return await self.primary.complete(messages, tools=tools)
        except (httpx.HTTPError, KeyError, ValueError, TypeError, json.JSONDecodeError):
            self.fallback_count += 1
            return await self.fallback.complete(messages, tools=tools)


class ScriptedModel(CodingModel):
    """Deterministic model used by tests and offline demos."""

    def __init__(self, turns: list[ModelTurn]):
        self.turns = list(turns)
        self.messages: list[list[dict[str, Any]]] = []

    async def complete(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelTurn:
        self.messages.append(list(messages))
        if not self.turns:
            return ModelTurn(content="No further action is required.", model="scripted")
        return self.turns.pop(0)


class ABModelRouter(CodingModel):
    def __init__(self, primary: CodingModel, candidate: CodingModel, *, candidate_percent: int = 0):
        if not 0 <= candidate_percent <= 100:
            raise ValueError("candidate_percent must be between 0 and 100")
        self.primary = primary
        self.candidate = candidate
        self.candidate_percent = candidate_percent

    async def complete(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelTurn:
        stable = json.dumps(messages, ensure_ascii=False, sort_keys=True)
        bucket = sum(stable.encode("utf-8")) % 100
        selected = self.candidate if bucket < self.candidate_percent else self.primary
        return await selected.complete(messages, tools=tools)
