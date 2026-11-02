"""Tests for settings loading and secret handling."""

from __future__ import annotations

import pytest

from mcp_teamcity.settings import TeamCitySettings


def test_loads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEAMCITY_BASE_URL", "https://tc.test")
    monkeypatch.setenv("TEAMCITY_TOKEN", "secret-token")
    settings = TeamCitySettings()
    assert settings.base_url == "https://tc.test"
    assert settings.token == "secret-token"


def test_defaults() -> None:
    settings = TeamCitySettings(base_url="https://tc.test", token="t")
    assert settings.transport == "stdio"
    assert settings.http_port == 8080
    assert settings.log_format == "json"
    assert settings.log_level == "INFO"
    assert settings.default_limit == 50
    assert settings.max_limit == 500
    assert settings.index_refresh_interval == 300
    assert settings.otel_enabled is False
    assert settings.otel_service_name == "readonly-mcp-teamcity"


def test_token_hidden_in_repr() -> None:
    settings = TeamCitySettings(base_url="https://tc.test", token="super-secret")
    assert "super-secret" not in repr(settings)


def test_env_prefix_applies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEAMCITY_BASE_URL", "https://tc.test")
    monkeypatch.setenv("TEAMCITY_TOKEN", "t")
    monkeypatch.setenv("TEAMCITY_DEFAULT_LIMIT", "10")
    monkeypatch.setenv("TEAMCITY_TRANSPORT", "http")
    settings = TeamCitySettings()
    assert settings.default_limit == 10
    assert settings.transport == "http"


def test_http_host_defaults_to_loopback() -> None:
    settings = TeamCitySettings(base_url="https://tc.test", token="t")
    assert settings.http_host == "127.0.0.1"


def test_is_loopback() -> None:
    from mcp_teamcity.__main__ import is_loopback

    assert is_loopback("127.0.0.1")
    assert is_loopback("::1")
    assert is_loopback("localhost")
    assert not is_loopback("0.0.0.0")
    assert not is_loopback("192.168.1.10")
