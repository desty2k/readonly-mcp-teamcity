"""Tests for test-result tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
from helpers import extract_tools

from mcp_teamcity.tools import tests as tests_tool


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://tc.example.com/x")
    response = httpx.Response(status, request=request, text="boom")
    return httpx.HTTPStatusError("err", request=request, response=response)


async def test_results_shapes_response(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(
        return_value={
            "count": 1,
            "testOccurrence": [
                {
                    "id": "id:1,build:(id:99)",
                    "name": "com.example.Test.method",
                    "status": "FAILURE",
                    "duration": 120,
                    "details": "AssertionError",
                    "test": {"id": "t1"},
                }
            ],
        }
    )
    tools = extract_tools(tests_tool)
    result = await tools["get_build_test_results"](mock_ctx, build_id="99", status="FAILURE")
    t = result["tests"][0]
    assert t["status"] == "FAILURE"
    assert t["duration_ms"] == 120
    assert t["test_id"] == "t1"


async def test_results_empty(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(return_value={"count": 0, "testOccurrence": []})
    tools = extract_tools(tests_tool)
    result = await tools["get_build_test_results"](mock_ctx, build_id="99")
    assert result["tests"] == []


async def test_details_shapes_response(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(
        return_value={
            "id": "id:1,build:(id:99)",
            "name": "com.example.Test.method",
            "status": "FAILURE",
            "duration": 120,
            "details": "stacktrace",
            "test": {"id": "t1", "name": "com.example.Test.method"},
        }
    )
    tools = extract_tools(tests_tool)
    result = await tools["get_test_details"](mock_ctx, test_locator="id:1,build:(id:99)")
    assert result["status"] == "FAILURE"
    assert result["details"] == "stacktrace"
    assert result["test_name"] == "com.example.Test.method"


async def test_details_not_found(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(side_effect=_http_error(404))
    tools = extract_tools(tests_tool)
    result = await tools["get_test_details"](mock_ctx, test_locator="build:(id:1),id:0")
    assert "not found" in result["error"]
