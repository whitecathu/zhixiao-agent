import httpx
import pytest

from zhixiao_agent.model import (
    FallbackModel,
    ModelProfile,
    OpenAICompatibleModel,
    ScriptedModel,
)
from zhixiao_agent.types import ModelTurn


@pytest.mark.asyncio
async def test_openai_compatible_model_tracks_tokens_and_cost() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = OpenAICompatibleModel(
        ModelProfile(
            provider="test",
            model="test-model",
            api_base="https://model.test/v1",
            api_key="secret",
            input_cost_per_million=1.0,
            output_cost_per_million=2.0,
        ),
        client=client,
    )
    turn = await model.complete([{"role": "user", "content": "hello"}])
    await client.aclose()
    assert turn.cost_usd == pytest.approx(0.0002)
    assert model.usage.requests == 1
    assert model.usage.prompt_tokens == 100


@pytest.mark.asyncio
async def test_fallback_model_uses_backup_after_transport_failure() -> None:
    class BrokenModel(ScriptedModel):
        async def complete(self, messages, *, tools=None):
            raise httpx.ConnectError("unavailable")

    backup = ScriptedModel([ModelTurn(content="fallback", model="backup")])
    model = FallbackModel(BrokenModel([]), backup)
    turn = await model.complete([{"role": "user", "content": "hello"}])
    assert turn.model == "backup"
    assert model.fallback_count == 1


@pytest.mark.asyncio
async def test_openai_compatible_model_retries_429_and_honors_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
        )

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("zhixiao_agent.model.asyncio.sleep", fake_sleep)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = OpenAICompatibleModel(
        ModelProfile(
            provider="test",
            model="test-model",
            api_base="https://model.test/v1",
            api_key="secret",
            max_retries=1,
        ),
        client=client,
    )
    turn = await model.complete([{"role": "user", "content": "hello"}])
    await client.aclose()

    assert turn.content == "ok"
    assert calls == 2
    assert sleeps == [0.0]
