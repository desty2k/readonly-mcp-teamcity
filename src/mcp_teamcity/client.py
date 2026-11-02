"""Async TeamCity REST API client.

A thin wrapper over a single ``httpx.AsyncClient`` with bearer-token auth,
connection pooling, retries, and OpenTelemetry child spans around each upstream
call. All tools reach the API through :meth:`TeamCityClient.get` and
:meth:`TeamCityClient.get_text`.

TeamCity authenticates with a static ``Authorization: Bearer <token>`` header —
there is no per-request signing — so the header is set once on the client.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import orjson
from fastmcp.telemetry import get_tracer

from mcp_teamcity.settings import TeamCitySettings

logger = logging.getLogger(__name__)


class TeamCityClient:
    """HTTP client for the TeamCity REST API."""

    def __init__(self, settings: TeamCitySettings) -> None:
        transport = httpx.AsyncHTTPTransport(
            retries=settings.max_retries,
            limits=httpx.Limits(
                max_connections=settings.pool_max_connections,
                max_keepalive_connections=settings.pool_max_connections,
            ),
        )
        self._http = httpx.AsyncClient(
            base_url=settings.base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {settings.token}",
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(settings.timeout, connect=10.0),
            transport=transport,
        )
        # No-op tracer unless an OpenTelemetry SDK is configured; child spans
        # nest under FastMCP's tool/call span to surface TeamCity API latency.
        self._tracer = get_tracer()

    async def close(self) -> None:
        await self._http.aclose()

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Send a GET request and return the parsed JSON response."""
        with self._tracer.start_as_current_span("teamcity_api.GET") as span:
            span.set_attribute("http.request.method", "GET")
            span.set_attribute("url.path", path)
            response = await self._http.get(path, params=params)
            span.set_attribute("http.response.status_code", response.status_code)

            if response.status_code >= 400:
                logger.warning(
                    "api_error GET %s status=%d body=%s",
                    path,
                    response.status_code,
                    response.text[:500],
                )
                response.raise_for_status()

            return orjson.loads(response.content)

    async def get_text(self, path: str, params: dict[str, Any] | None = None) -> str:
        """Send a GET request and return the raw response body as text.

        Used for endpoints that return plain text rather than JSON, such as
        ``/downloadBuildLog.html``.
        """
        with self._tracer.start_as_current_span("teamcity_api.GET") as span:
            span.set_attribute("http.request.method", "GET")
            span.set_attribute("url.path", path)
            response = await self._http.get(path, params=params, headers={"Accept": "text/plain"})
            span.set_attribute("http.response.status_code", response.status_code)

            if response.status_code >= 400:
                logger.warning(
                    "api_error GET %s status=%d body=%s",
                    path,
                    response.status_code,
                    response.text[:500],
                )
                response.raise_for_status()

            return response.text
