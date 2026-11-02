"""Tests for project tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
from helpers import extract_tools

from mcp_teamcity.tools import projects


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://tc.example.com/x")
    response = httpx.Response(status, request=request, text="boom")
    return httpx.HTTPStatusError("err", request=request, response=response)


async def test_search_projects_shapes_response(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(
        return_value={
            "count": 1,
            "nextHref": "/next",
            "project": [
                {
                    "id": "Proj",
                    "name": "My Project",
                    "description": "desc",
                    "archived": False,
                    "parentProjectId": "_Root",
                    "buildTypes": {"count": 5},
                    "projects": {"count": 2},
                    "internalField": "stripped",
                }
            ],
        }
    )
    tools = extract_tools(projects)
    result = await tools["search_projects"](mock_ctx, project_id="Proj")

    assert result["count"] == 1
    proj = result["projects"][0]
    assert proj["id"] == "Proj"
    assert proj["build_config_count"] == 5
    assert proj["child_project_count"] == 2
    assert "internalField" not in proj
    assert result["pagination"]["has_next_page"] is True


async def test_search_projects_empty(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(return_value={"count": 0, "project": []})
    tools = extract_tools(projects)
    result = await tools["search_projects"](mock_ctx)
    assert result["projects"] == []
    assert result["count"] == 0


async def test_get_project_details_shapes_response(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(
        return_value={
            "id": "Proj",
            "name": "My Project",
            "parentProject": {"id": "_Root", "name": "Root"},
            "buildTypes": {"buildType": [{"id": "Proj_Build", "name": "Build", "paused": False}]},
            "projects": {"project": [{"id": "Sub", "name": "Sub"}]},
            "parameters": {"property": [{"name": "env", "value": "prod"}]},
        }
    )
    tools = extract_tools(projects)
    result = await tools["get_project_details"](mock_ctx, project_id="Proj")

    assert result["id"] == "Proj"
    assert result["build_config_count"] == 1
    assert result["child_project_count"] == 1
    assert result["parameters"] == {"env": "prod"}
    assert result["parent_project"] == {"id": "_Root", "name": "Root"}


async def test_get_project_details_not_found(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(side_effect=_http_error(404))
    tools = extract_tools(projects)
    result = await tools["get_project_details"](mock_ctx, project_id="Missing")
    assert "not found" in result["error"]
