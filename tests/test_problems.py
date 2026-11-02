"""Tests for build-problem and investigation tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
from helpers import extract_tools

from mcp_teamcity.tools import problems


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://tc.example.com/x")
    response = httpx.Response(status, request=request, text="boom")
    return httpx.HTTPStatusError("err", request=request, response=response)


async def test_problems_shapes_response(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(
        return_value={
            "count": 1,
            "problemOccurrence": [
                {
                    "id": "p1",
                    "type": "TC_EXIT_CODE",
                    "identity": "exitCode",
                    "details": "Process exited with code 1",
                    "problem": {"id": "1", "type": "TC_EXIT_CODE", "description": "exit 1"},
                }
            ],
        }
    )
    tools = extract_tools(problems)
    result = await tools["get_build_problems"](mock_ctx, build_id="99")
    p = result["problems"][0]
    assert p["type"] == "TC_EXIT_CODE"
    assert p["problem_description"] == "exit 1"


async def test_problems_not_found(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(side_effect=_http_error(404))
    tools = extract_tools(problems)
    result = await tools["get_build_problems"](mock_ctx, build_id="0")
    assert "not found" in result["error"]


async def test_investigations_shapes_response(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(
        return_value={
            "count": 1,
            "investigation": [
                {
                    "id": "inv1",
                    "state": "TAKEN",
                    "assignee": {"username": "bob", "name": "Bob"},
                    "assignment": {"text": "looking into it", "user": {"username": "alice"}},
                    "scope": {
                        "buildTypes": {"buildType": [{"id": "Proj_Build", "name": "Build", "projectId": "Proj"}]},
                        "project": {"id": "Proj", "name": "Proj"},
                    },
                    "resolution": {"type": "whenFixed"},
                }
            ],
        }
    )
    tools = extract_tools(problems)
    result = await tools["search_investigations"](mock_ctx, project_id="Proj")
    inv = result["investigations"][0]
    assert inv["assignee"] == "bob"
    assert inv["assigned_by"] == "alice"
    assert inv["scope_build_types"][0]["id"] == "Proj_Build"
    assert inv["scope_project"]["name"] == "Proj"


async def test_investigations_empty(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(return_value={"count": 0, "investigation": []})
    tools = extract_tools(problems)
    result = await tools["search_investigations"](mock_ctx)
    assert result["investigations"] == []


async def test_list_muted_tests_shapes_response(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(
        return_value={
            "count": 1,
            "mute": [
                {
                    "id": 5,
                    "assignment": {"text": "flaky, tracked in JIRA", "user": {"username": "carol"}},
                    "scope": {
                        "project": {"id": "Proj", "name": "Proj"},
                        "buildTypes": {"buildType": [{"id": "Proj_Build", "name": "Build"}]},
                    },
                    "target": {"tests": {"test": [{"id": "t1", "name": "com.example.FlakyTest"}]}},
                    "resolution": {"type": "manually"},
                }
            ],
        }
    )
    tools = extract_tools(problems)
    result = await tools["list_muted_tests"](mock_ctx, project_id="Proj")
    m = result["mutes"][0]
    assert m["tests"] == ["com.example.FlakyTest"]
    assert m["muted_by"] == "carol"
    assert m["scope_project"]["id"] == "Proj"
    assert m["scope_build_types"][0]["id"] == "Proj_Build"
    assert m["resolution_type"] == "manually"


async def test_list_muted_tests_empty(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(return_value={"count": 0, "mute": []})
    tools = extract_tools(problems)
    result = await tools["list_muted_tests"](mock_ctx)
    assert result["mutes"] == []
