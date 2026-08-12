from __future__ import annotations

import httpx
import pytest

from zhixiao_agent.tools.mcp_adapter import (
    build_mcp_handler,
    load_mcp_adapter_config,
    mcp_config_from_env,
    parse_mcp_whitelist,
)


def test_parse_mcp_whitelist_splits_pairs() -> None:
    assert parse_mcp_whitelist("") == []
    assert parse_mcp_whitelist(" local:read , docs:search ") == ["local:read", "docs:search"]


def test_mcp_config_from_env_builds_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_WHITELIST", "local:read")
    monkeypatch.setenv("MCP_HTTP_BASE", "https://mcp.example")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "mcp.example")
    monkeypatch.delenv("MCP_ENABLED", raising=False)
    metadata = mcp_config_from_env()
    assert metadata is not None
    assert metadata["mcp_whitelist"] == ["local:read"]
    assert callable(metadata["mcp"])


def test_mcp_config_from_env_absent_when_unconfigured() -> None:
    assert mcp_config_from_env({}) is None


def test_build_mcp_handler_invokes_registered_callable() -> None:
    handler = build_mcp_handler(
        {
            "whitelist": ["local:echo"],
            "callables": {"local:echo": lambda arguments: {"echo": arguments}},
        }
    )
    assert handler("local", "echo", {"path": "README.md"}) == {"echo": {"path": "README.md"}}


def test_build_mcp_handler_posts_http(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        content = b'{"ok": true}'
        text = '{"ok": true}'

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, bool]:
            return {"ok": True}

    def fake_post(url: str, json: dict, timeout: float) -> FakeResponse:
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    handler = build_mcp_handler(
        {
            "http_base": "https://mcp.example",
            "allowed_hosts": ["mcp.example"],
            "whitelist": ["svc:tool"],
        }
    )
    assert handler("svc", "tool", {"q": 1}) == {"ok": True}
    assert captured["url"] == "https://mcp.example/mcp/svc/tool"


def test_build_mcp_handler_raises_without_transport() -> None:
    handler = build_mcp_handler({"whitelist": ["local:read"]})
    with pytest.raises(RuntimeError, match="no MCP transport"):
        handler("local", "read", {})


@pytest.mark.parametrize(
    "target",
    [
        "../local:read",
        "local:../read",
        "local/read:tool",
        r"local\read:tool",
        "local:read%2Fsecret",
        "local:read%5csecret",
        "local:read:extra",
        ".:read",
        "local:..",
    ],
)
def test_mcp_whitelist_rejects_unsafe_identifiers(target: str) -> None:
    with pytest.raises(ValueError, match="invalid MCP"):
        parse_mcp_whitelist(target)


def test_build_mcp_handler_rechecks_exact_whitelist() -> None:
    handler = build_mcp_handler(
        {"callables": {"local:echo": lambda arguments: {"echo": arguments}}}
    )
    with pytest.raises(PermissionError, match="not whitelisted"):
        handler("local", "echo", {"value": 1})


def test_build_mcp_handler_rejects_encoded_identifier() -> None:
    handler = build_mcp_handler({"whitelist": ["local:read"]})
    with pytest.raises(ValueError, match="invalid MCP tool"):
        handler("local", "read%2Fsecret", {})


def test_local_handlers_do_not_expand_whitelist() -> None:
    metadata = mcp_config_from_env(
        {
            "MCP_LOCAL_HANDLERS": '{"local:read": {"ok": true}}',
            "MCP_ENABLED": "true",
        }
    )
    assert metadata is not None
    assert metadata["mcp_whitelist"] == []
    with pytest.raises(PermissionError, match="not whitelisted"):
        metadata["mcp"]("local", "read", {})


@pytest.mark.parametrize(
    ("http_base", "allowed_hosts", "message"),
    [
        ("ftp://mcp.example", "mcp.example", "http or https"),
        ("http://mcp.example", "mcp.example", "requires https"),
        ("https://mcp.example", "", "must explicitly allow"),
        ("https://mcp.example", "other.example", "not in MCP_ALLOWED_HOSTS"),
        ("https://user@mcp.example", "mcp.example", "user information"),
    ],
)
def test_mcp_http_base_rejects_unsafe_configuration(
    http_base: str,
    allowed_hosts: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        load_mcp_adapter_config(
            {
                "MCP_HTTP_BASE": http_base,
                "MCP_ALLOWED_HOSTS": allowed_hosts,
            }
        )


def test_mcp_http_base_allows_explicit_local_development_host() -> None:
    config = load_mcp_adapter_config(
        {
            "MCP_HTTP_BASE": "http://127.0.0.1:9000",
            "MCP_ALLOWED_HOSTS": "127.0.0.1",
        }
    )
    assert config.http_base == "http://127.0.0.1:9000"
