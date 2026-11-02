"""Tests for logging configuration and formatters."""

from __future__ import annotations

import json
import logging
import sys

from mcp_teamcity.logging_config import (
    JsonFormatter,
    TextFormatter,
    _sanitize_message,
    configure_logging,
)


def _record(msg: str, *, exc_info=None) -> logging.LogRecord:
    return logging.LogRecord("teamcity", logging.INFO, __file__, 1, msg, None, exc_info)


def test_sanitize_strips_ansi_and_newlines() -> None:
    assert _sanitize_message("\x1b[92mhi\x1b[0m") == "hi"
    assert _sanitize_message("a\nb") == "a\\nb"


def test_json_formatter_produces_valid_json() -> None:
    out = JsonFormatter().format(_record("server_ready count=3"))
    data = json.loads(out)
    assert data["level"] == "INFO"
    assert data["logger"] == "teamcity"
    assert data["message"] == "server_ready count=3"
    assert data["service"] == "readonly-mcp-teamcity"
    assert "version" in data


def test_json_formatter_includes_exception() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        out = JsonFormatter().format(_record("failed", exc_info=sys.exc_info()))
    data = json.loads(out)
    assert "ValueError" in data["exception"]
    assert "traceback" in data


def test_text_formatter_single_line() -> None:
    out = TextFormatter().format(_record("hello"))
    assert "[INFO]" in out
    assert "teamcity: hello" in out
    assert "\n" not in out


def test_configure_logging_returns_uvicorn_config() -> None:
    cfg = configure_logging(log_format="json", log_level="DEBUG")
    assert cfg["version"] == 1
    assert "uvicorn" in cfg["loggers"]
    assert cfg["formatters"]["default"]["()"] == "mcp_teamcity.logging_config.JsonFormatter"
    # Root logger now has exactly one stderr handler.
    root = logging.getLogger()
    assert len(root.handlers) == 1
