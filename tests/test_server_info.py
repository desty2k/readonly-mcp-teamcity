"""Tests for the server-info tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
from helpers import extract_tools

from mcp_teamcity.tools import server_info


async def test_server_info_shapes_response(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(
        return_value={
            "version": "2024.03.1",
            "versionMajor": 2024,
            "versionMinor": 3,
            "buildNumber": "147512",
            "startTime": "20240101T000000+0000",
            "currentTime": "20240601T120000+0000",
            "webUrl": "https://tc.example.com",
            "internalField": "stripped",
        }
    )
    tools = extract_tools(server_info)
    result = await tools["get_server_info"](mock_ctx)
    assert result["version"] == "2024.03.1"
    assert result["build_number"] == "147512"
    assert "internalField" not in result


async def test_server_info_connection_error(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    request = httpx.Request("GET", "https://tc.example.com/app/rest/server")
    client.get = AsyncMock(side_effect=httpx.ConnectError("refused", request=request))
    tools = extract_tools(server_info)
    result = await tools["get_server_info"](mock_ctx)
    assert "Failed to connect" in result["error"]


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://tc.example.com/x")
    response = httpx.Response(status, request=request, text="forbidden")
    return httpx.HTTPStatusError("err", request=request, response=response)


async def test_server_health_combines_sources(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(
        side_effect=[
            {"healthItem": [{"identity": "disk-low", "severity": "WARN", "healthCategory": {"name": "Disk"}}]},
            {"metric": [{"name": "cpuUsage", "value": 0.5}, {"name": "buildQueueSize", "value": 3}]},
        ]
    )
    tools = extract_tools(server_info)
    result = await tools["get_server_health"](mock_ctx)
    assert result["health_item_count"] == 1
    assert result["health_items"][0]["category"] == "Disk"
    assert result["metrics"]["cpuUsage"] == 0.5
    assert result["notes"] == []


async def test_server_health_degrades_per_endpoint(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    # Health items forbidden, metrics OK — partial result with a note.
    client.get = AsyncMock(side_effect=[_http_error(403), {"metric": [{"name": "cpuUsage", "value": 0.1}]}])
    tools = extract_tools(server_info)
    result = await tools["get_server_health"](mock_ctx)
    assert result["health_items"] == []
    assert result["metrics"]["cpuUsage"] == 0.1
    assert any("health items unavailable" in n for n in result["notes"])
