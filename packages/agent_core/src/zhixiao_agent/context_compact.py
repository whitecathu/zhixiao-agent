from __future__ import annotations

import json
from typing import Any

DEFAULT_KEEP_PAIRS = 8
DEFAULT_CHAR_BUDGET = 60_000
_SUMMARY_TAG = "[conversation_summary]"
_MAX_BULLET_CHARS = 160
_IMMUTABLE_MARKERS = (
    "Request:",
    "Project instructions",
    "AGENTS.md",
    "AGENT.md",
    "Claude.md",
    "Approved plan:",
    "Permission:",
    "SKILL.md",
)


def message_char_count(messages: list[dict[str, Any]]) -> int:
    total = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total += len(content)
        elif content is not None:
            total += len(json.dumps(content, ensure_ascii=False))
        tool_calls = message.get("tool_calls")
        if tool_calls:
            total += len(json.dumps(tool_calls, ensure_ascii=False))
    return total


def compact_messages(
    messages: list[dict[str, Any]],
    *,
    keep_pairs: int = DEFAULT_KEEP_PAIRS,
    char_budget: int = DEFAULT_CHAR_BUDGET,
) -> list[dict[str, Any]]:
    """Compact older assistant/tool turns when the conversation exceeds the char budget.

    Keeps leading system prompts and the last ``keep_pairs`` message pairs verbatim.
    Older assistant/tool (and intervening user) messages collapse into one summary
    message tagged ``[conversation_summary]``.
    """
    if keep_pairs < 1:
        raise ValueError("keep_pairs must be >= 1")
    if char_budget < 1:
        raise ValueError("char_budget must be >= 1")
    if message_char_count(messages) <= char_budget:
        return list(messages)

    leading, body = _split_leading_immutable(messages)
    keep_count = keep_pairs * 2
    if len(body) <= keep_count:
        return list(messages)

    cut = len(body) - keep_count
    # Avoid orphaning tool results from their assistant tool_calls message.
    while cut > 0 and body[cut].get("role") == "tool":
        cut -= 1
    if cut <= 0:
        return list(messages)

    older = body[:cut]
    recent = body[cut:]
    summary = _build_summary_message(older)
    if summary is None:
        return leading + recent
    return leading + [summary] + recent


def maybe_compact_messages(
    messages: list[dict[str, Any]],
    *,
    keep_pairs: int = DEFAULT_KEEP_PAIRS,
    char_budget: int = DEFAULT_CHAR_BUDGET,
) -> list[dict[str, Any]]:
    """Return messages unchanged when under budget; otherwise compact."""
    if message_char_count(messages) <= char_budget:
        return list(messages)
    return compact_messages(messages, keep_pairs=keep_pairs, char_budget=char_budget)


def _split_leading_immutable(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    leading: list[dict[str, Any]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        content = message.get("content") or ""
        if isinstance(content, str) and _SUMMARY_TAG in content:
            break
        is_system = message.get("role") == "system"
        is_immutable_user = message.get("role") == "user" and isinstance(content, str) and any(
            marker in content for marker in _IMMUTABLE_MARKERS
        )
        if not (is_system or is_immutable_user):
            break
        leading.append(message)
        index += 1
    return leading, list(messages[index:])


def _build_summary_message(older: list[dict[str, Any]]) -> dict[str, Any] | None:
    bullets: list[str] = []
    for message in older:
        role = message.get("role")
        if role == "assistant":
            bullets.append(_summarize_assistant(message))
        elif role == "tool":
            bullets.append(_summarize_tool(message))
        elif role == "user":
            text = _shorten(str(message.get("content") or ""))
            if text:
                bullets.append(f"- user: {text}")
        elif role == "system":
            content = str(message.get("content") or "")
            if _SUMMARY_TAG in content:
                # Preserve prior summary bullets without re-wrapping the tag.
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("- "):
                        bullets.append(stripped)
    if not bullets:
        return None
    return {
        "role": "system",
        "content": f"{_SUMMARY_TAG}\n" + "\n".join(bullets),
    }


def _summarize_assistant(message: dict[str, Any]) -> str:
    content = _shorten(str(message.get("content") or "").strip())
    tool_names: list[str] = []
    for call in message.get("tool_calls") or []:
        if isinstance(call, dict):
            function = call.get("function") or {}
            name = function.get("name") or call.get("name")
            if name:
                tool_names.append(str(name))
    if tool_names:
        tools = ", ".join(tool_names)
        status = "calling tools"
        if content:
            return f"- assistant ({status}; tools={tools}): {content}"
        return f"- assistant ({status}; tools={tools})"
    if content:
        return f"- assistant (ok): {content}"
    return "- assistant (ok): (empty)"


def _summarize_tool(message: dict[str, Any]) -> str:
    name = str(message.get("name") or "tool")
    status = "ok"
    summary = ""
    raw = message.get("content")
    if isinstance(raw, str) and raw.strip():
        try:
            payload = json.loads(raw.removesuffix("...[truncated]"))
        except json.JSONDecodeError:
            summary = _shorten(raw)
        else:
            if isinstance(payload, dict):
                status = str(payload.get("status") or status)
                summary = _shorten(str(payload.get("summary") or ""))
            else:
                summary = _shorten(raw)
    if summary:
        return f"- tool {name} ({status}): {summary}"
    return f"- tool {name} ({status})"


def _shorten(text: str, limit: int = _MAX_BULLET_CHARS) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3] + "..."
