from zhixiao_agent.context_compact import (
    compact_messages,
    maybe_compact_messages,
    message_char_count,
)


def _tool(name: str, summary: str, *, status: str = "success") -> dict:
    return {
        "role": "tool",
        "tool_call_id": f"call-{name}",
        "name": name,
        "content": (
            f'{{"status": "{status}", "summary": "{summary}", '
            f'"data": null, "next_actions": [], "artifacts": [], '
            f'"root_cause": null, "retry": null, "stop_condition": null}}'
        ),
    }


def _assistant_with_tool(name: str, content: str = "") -> dict:
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [
            {
                "id": f"call-{name}",
                "type": "function",
                "function": {"name": name, "arguments": "{}"},
            }
        ],
    }


def test_under_budget_messages_are_unchanged() -> None:
    messages = [
        {"role": "system", "content": "You are Zhixiao."},
        {"role": "user", "content": "Inspect README."},
        {"role": "assistant", "content": "Done."},
    ]
    assert maybe_compact_messages(messages, char_budget=10_000) == messages
    assert message_char_count(messages) < 10_000


def test_compacts_older_tool_and_assistant_into_summary() -> None:
    messages: list[dict] = [
        {"role": "system", "content": "You are Zhixiao."},
        {"role": "user", "content": "Explore the repository structure carefully."},
    ]
    for index in range(12):
        tool_name = "read_file" if index % 2 == 0 else "grep"
        messages.append(_assistant_with_tool(tool_name, content=f"step-{index} " + ("x" * 200)))
        messages.append(_tool(tool_name, f"read chunk {index} " + ("y" * 200)))
    messages.append({"role": "assistant", "content": "Final recent answer."})
    messages.append({"role": "user", "content": "Continue."})

    compacted = compact_messages(messages, keep_pairs=2, char_budget=500)

    assert compacted[0]["role"] == "system"
    assert compacted[0]["content"] == "You are Zhixiao."
    summary = next(msg for msg in compacted if "[conversation_summary]" in str(msg.get("content", "")))
    assert summary["role"] == "system"
    assert "- assistant" in summary["content"]
    assert "- tool" in summary["content"]
    assert "read_file" in summary["content"] or "grep" in summary["content"]
    # Last pairs stay verbatim.
    assert compacted[-2]["content"] == "Final recent answer."
    assert compacted[-1]["content"] == "Continue."
    assert message_char_count(compacted) < message_char_count(messages)


def test_does_not_orphan_tool_results_from_assistant_calls() -> None:
    messages: list[dict] = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "start"},
    ]
    for index in range(6):
        messages.append(_assistant_with_tool(f"read_file", content=f"a{index}" + ("z" * 300)))
        messages.append(_tool("read_file", f"payload {index}" + ("w" * 300)))

    compacted = compact_messages(messages, keep_pairs=1, char_budget=200)
    # Recent window must not begin with a dangling tool message.
    recent_roles = [msg["role"] for msg in compacted if msg.get("role") != "system"]
    assert "tool" not in recent_roles[:1] or recent_roles[0] != "tool"
    for index, role in enumerate(recent_roles):
        if role == "tool":
            assert index > 0
            assert recent_roles[index - 1] in {"assistant", "tool"}
