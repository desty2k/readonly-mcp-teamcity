"""Entry point: python -m mcp_teamcity."""

from __future__ import annotations

import ipaddress
import logging

from mcp_teamcity.logging_config import configure_logging
from mcp_teamcity.settings import TeamCitySettings

logger = logging.getLogger(__name__)


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def main() -> None:
    settings = TeamCitySettings()  # type: ignore[call-arg]

    # Configure unified logging before anything else runs.
    uvicorn_log_config = configure_logging(
        log_format=settings.log_format,
        log_level=settings.log_level,
    )

    # Set up the OpenTelemetry SDK before the server is built. No-op when
    # TEAMCITY_OTEL_ENABLED is false, so the default behavior is unchanged.
    from mcp_teamcity.telemetry import configure_telemetry

    configure_telemetry(settings)

    from mcp_teamcity.server import create_server

    mcp = create_server(settings)

    logger.info("starting transport=%s", settings.transport)
    if settings.transport != "stdio" and not is_loopback(settings.http_host):
        logger.warning(
            "http_unauthenticated host=%s port=%d: the %s transport has no authentication; anyone who can reach "
            "this address can read TeamCity with the configured token",
            settings.http_host,
            settings.http_port,
            settings.transport,
        )

    if settings.transport == "http":
        mcp.run(
            transport="streamable-http",
            host=settings.http_host,
            port=settings.http_port,
            stateless_http=True,
            show_banner=False,
            uvicorn_config={"log_config": uvicorn_log_config},
        )
    elif settings.transport == "sse":
        mcp.run(
            transport="sse",
            host=settings.http_host,
            port=settings.http_port,
            show_banner=False,
            uvicorn_config={"log_config": uvicorn_log_config},
        )
    else:
        mcp.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
