"""Configuration from environment variables."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TeamCitySettings(BaseSettings):
    """TeamCity MCP server settings loaded from TEAMCITY_* environment variables."""

    model_config = SettingsConfigDict(env_prefix="TEAMCITY_")

    # TeamCity connection (required)
    base_url: str
    token: str = Field(repr=False)

    # HTTP client tuning
    timeout: int = 30
    max_retries: int = 3
    pool_max_connections: int = 20

    # Pagination defaults
    default_limit: int = 50
    max_limit: int = 500

    # Build-config index refresh interval (seconds) — powers fuzzy search.
    index_refresh_interval: int = 300

    # Build-log cache: total size cap (bytes, approximate) and entry lifetime.
    # Logs of running builds are never cached.
    log_cache_max_bytes: int = 64 * 1024 * 1024
    log_cache_ttl: int = 300

    # Transport
    transport: Literal["stdio", "http", "sse"] = "stdio"
    # The HTTP/SSE transports have no authentication: anyone who can reach the
    # port can read TeamCity with this server's token. Loopback by default.
    http_host: str = "127.0.0.1"
    http_port: int = 8080

    # Logging
    log_format: Literal["json", "text"] = "json"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # --- OpenTelemetry tracing (optional) ---
    # Disabled by default: when off, no SDK is configured and FastMCP's native
    # instrumentation stays a no-op, so the server behaves exactly as before.
    # Requires the `otel` extra to be installed (opentelemetry-sdk + exporter).
    otel_enabled: bool = False
    otel_service_name: str = "readonly-mcp-teamcity"
    # OTLP collector endpoint. When left unset, the exporter falls back to the
    # standard OTEL_EXPORTER_OTLP_ENDPOINT env var (or localhost:4317 / :4318).
    otel_endpoint: str | None = None
    otel_protocol: Literal["grpc", "http/protobuf"] = "grpc"
    # Also print spans to stderr — handy for local debugging without a collector.
    otel_console_export: bool = False
