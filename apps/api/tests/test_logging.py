import sys
from typing import Any

from app.core import logging as logging_config


def test_logging_defaults_to_stdout_without_workspace_writes(monkeypatch) -> None:
    sinks: list[Any] = []
    monkeypatch.setattr(logging_config.settings, "LOG_FILE", "")
    monkeypatch.setattr(logging_config.logger, "remove", lambda: None)
    monkeypatch.setattr(logging_config.logger, "configure", lambda **_: None)
    monkeypatch.setattr(
        logging_config.logger,
        "add",
        lambda sink, **_: sinks.append(sink),
    )

    logging_config.setup_logging()

    assert sinks == [sys.stdout]


def test_file_logging_requires_an_explicit_writable_path(monkeypatch) -> None:
    sinks: list[Any] = []
    monkeypatch.setattr(logging_config.settings, "LOG_FILE", "writable/service.log")
    monkeypatch.setattr(logging_config.logger, "remove", lambda: None)
    monkeypatch.setattr(logging_config.logger, "configure", lambda **_: None)
    monkeypatch.setattr(
        logging_config.logger,
        "add",
        lambda sink, **_: sinks.append(sink),
    )

    logging_config.setup_logging()

    assert sinks == [sys.stdout, "writable/service.log"]
