"""Tests for optional OpenTelemetry wiring (without touching global state)."""

from __future__ import annotations

import pytest

from mcp_teamcity import telemetry
from mcp_teamcity.settings import TeamCitySettings


def _settings(**overrides: object) -> TeamCitySettings:
    base = {"base_url": "https://tc.test", "token": "t"}
    base.update(overrides)
    return TeamCitySettings(**base)  # type: ignore[arg-type]


def test_build_tracer_provider_disabled_returns_none() -> None:
    assert telemetry.build_tracer_provider(_settings(otel_enabled=False)) is None


def test_configure_telemetry_disabled_returns_false() -> None:
    assert telemetry.configure_telemetry(_settings(otel_enabled=False)) is False


def test_build_tracer_provider_enabled_returns_provider() -> None:
    # The dev extra installs the OpenTelemetry SDK, so a provider is built.
    provider = telemetry.build_tracer_provider(_settings(otel_enabled=True))
    assert provider is not None
    # It carries our resource attributes.
    attrs = provider.resource.attributes
    assert attrs["service.name"] == "readonly-mcp-teamcity"


def test_configure_telemetry_registers_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from opentelemetry import trace

    registered: list[object] = []
    monkeypatch.setattr(trace, "set_tracer_provider", lambda p: registered.append(p))
    monkeypatch.setattr(telemetry, "_configured", False)

    assert telemetry.configure_telemetry(_settings(otel_enabled=True)) is True
    assert len(registered) == 1
