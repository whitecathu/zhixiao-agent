from app.core.logging import redact_message


def test_redact_message_hides_common_secret_shapes() -> None:
    message = (
        "Authorization: Bearer abc.def.ghi "
        "api_key=sk-secret password=hunter2 token: refresh-value"
    )
    redacted = redact_message(message)
    assert "abc.def.ghi" not in redacted
    assert "sk-secret" not in redacted
    assert "hunter2" not in redacted
    assert "refresh-value" not in redacted
    assert redacted.count("[REDACTED]") == 4
