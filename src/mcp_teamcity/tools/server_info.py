"""Server-info tool — TeamCity version and status."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastmcp import Context, FastMCP

from mcp_teamcity.errors import api_error, connection_error

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def get_server_info(ctx: Context) -> dict[str, Any]:
        """Get TeamCity server version and status information.

        Returns the server version, build number, start time, and current time.
        Use this to verify connectivity or check which TeamCity version is running.

        Example questions:
            - "What version of TeamCity are we running?"
            - "Is TeamCity up?"
            - "When was TeamCity last restarted?"
        """
        app = ctx.lifespan_context
        client = app.client

        try:
            data = await client.get(
                "/app/rest/server",
                params={"fields": "version,versionMajor,versionMinor,buildNumber,startTime,currentTime,webUrl"},
            )
            if not isinstance(data, dict):
                return {"error": "Unexpected response from TeamCity server"}

            logger.info("get_server_info version=%s", data.get("version"))
            return {
                "version": data.get("version"),
                "version_major": data.get("versionMajor"),
                "version_minor": data.get("versionMinor"),
                "build_number": data.get("buildNumber"),
                "start_time": data.get("startTime"),
                "current_time": data.get("currentTime"),
                "web_url": data.get("webUrl"),
            }

        except httpx.HTTPStatusError as exc:
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)

    @mcp.tool()
    async def get_server_health(ctx: Context) -> dict[str, Any]:
        """Get server health items and runtime metrics.

        Combines TeamCity's reported health items (configuration/disk/plugin
        warnings) with runtime metrics (CPU, memory, queue size, etc.) — the
        two things that explain server-side ERROR builds or sluggishness. Each
        source degrades independently: if your token lacks permission for one,
        the other is still returned with a note.

        Returns:
            health_items (severity + category + identity), metrics (name -> value),
            and notes describing any source that was unavailable.

        Example questions:
            - "Is the TeamCity server healthy?"
            - "Are there any server health warnings?"
            - "What's the server's CPU / memory / queue load?"
        """
        app = ctx.lifespan_context
        client = app.client

        health_items: list[dict[str, Any]] = []
        metrics: dict[str, Any] = {}
        notes: list[str] = []

        try:
            try:
                h = await client.get(
                    "/app/rest/health",
                    params={"fields": "healthItem(identity,severity,healthCategory(id,name))"},
                )
                for item in h.get("healthItem", []) if isinstance(h, dict) else []:
                    category = item.get("healthCategory", {}) or {}
                    health_items.append(
                        {
                            "identity": item.get("identity"),
                            "severity": item.get("severity"),
                            "category": category.get("name"),
                        }
                    )
            except httpx.HTTPStatusError as exc:
                notes.append(f"health items unavailable (status {exc.response.status_code})")

            try:
                m = await client.get("/app/rest/server/metrics", params={"fields": "metric(name,value)"})
                for metric in m.get("metric", []) if isinstance(m, dict) else []:
                    metrics[metric.get("name")] = metric.get("value")
            except httpx.HTTPStatusError as exc:
                notes.append(f"metrics unavailable (status {exc.response.status_code})")

            logger.info("get_server_health health_items=%d metrics=%d", len(health_items), len(metrics))
            return {
                "health_items": health_items,
                "health_item_count": len(health_items),
                "metrics": metrics,
                "notes": notes,
            }

        except httpx.RequestError as exc:
            return connection_error(exc)
