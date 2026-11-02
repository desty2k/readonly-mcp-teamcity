"""Optional OpenTelemetry tracing setup.

FastMCP emits spans for every tool/resource/prompt call through the OpenTelemetry
*API*, which is a no-op until an SDK with a real ``TracerProvider`` is installed
and registered. This module wires up that SDK on demand.

It is entirely opt-in:

- When ``TEAMCITY_OTEL_ENABLED`` is false (the default), :func:`configure_telemetry`
  does nothing and the server runs exactly as it would without OpenTelemetry.
- When enabled but the ``otel`` extra is not installed, it logs a warning and
  degrades gracefully rather than crashing the server.

All exporter/endpoint behavior is driven by ``TEAMCITY_OTEL_*`` settings (see
:class:`mcp_teamcity.settings.TeamCitySettings`).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from . import __version__

if TYPE_CHECKING:
    from mcp_teamcity.settings import TeamCitySettings

logger = logging.getLogger(__name__)

# Guards against registering a TracerProvider more than once per process.
_configured = False


def build_tracer_provider(settings: TeamCitySettings) -> Any | None:
    """Construct a configured ``TracerProvider`` from settings, or ``None``.

    Returns ``None`` (no global side effects) when telemetry is disabled or the
    OpenTelemetry SDK is not installed. Kept separate from
    :func:`configure_telemetry` so it can be unit-tested without touching the
    process-global tracer provider.
    """
    if not settings.otel_enabled:
        return None

    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:  # pragma: no cover - exercised only without the otel extra
        logger.warning(
            "otel_enabled but the OpenTelemetry SDK is not installed; "
            "tracing disabled. Install the 'otel' extra: pip install 'readonly-mcp-teamcity[otel]'"
        )
        return None

    resource = Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.version": __version__,
        }
    )
    provider = TracerProvider(resource=resource)

    exporter = _build_otlp_exporter(settings)
    if exporter is not None:
        provider.add_span_processor(BatchSpanProcessor(exporter))

    if settings.otel_console_export:
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    return provider


def _build_otlp_exporter(settings: TeamCitySettings) -> Any | None:
    """Build the OTLP span exporter for the configured protocol.

    Passing the endpoint is optional: when unset the exporter reads the standard
    ``OTEL_EXPORTER_OTLP_ENDPOINT`` env var (or the protocol's default host).
    """
    kwargs: dict[str, Any] = {}
    if settings.otel_endpoint:
        kwargs["endpoint"] = settings.otel_endpoint

    if settings.otel_protocol == "http/protobuf":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    else:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    return OTLPSpanExporter(**kwargs)


def configure_telemetry(settings: TeamCitySettings) -> bool:
    """Register the global ``TracerProvider`` when telemetry is enabled.

    Should be called once during startup, before the FastMCP server is built.
    Returns ``True`` if tracing was activated, ``False`` otherwise. Safe to call
    when disabled or when the SDK is missing.
    """
    global _configured

    provider = build_tracer_provider(settings)
    if provider is None:
        return False

    if _configured:
        logger.debug("telemetry already configured; skipping")
        return True

    from opentelemetry import trace

    trace.set_tracer_provider(provider)
    _configured = True

    endpoint = settings.otel_endpoint or "default (OTEL_EXPORTER_OTLP_ENDPOINT)"
    logger.info(
        "telemetry_enabled service=%s protocol=%s endpoint=%s console=%s",
        settings.otel_service_name,
        settings.otel_protocol,
        endpoint,
        settings.otel_console_export,
    )
    return True
