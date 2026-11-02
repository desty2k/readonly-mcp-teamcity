"""Tests for build-configuration tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
from helpers import extract_tools

from mcp_teamcity.tools import build_configs


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://tc.example.com/x")
    response = httpx.Response(status, request=request, text="boom")
    return httpx.HTTPStatusError("err", request=request, response=response)


async def test_search_requires_filter(mock_ctx: MagicMock) -> None:
    tools = extract_tools(build_configs)
    result = await tools["search_build_configs"](mock_ctx)
    assert "error" in result
    mock_ctx.lifespan_context.client.get.assert_not_called()


async def test_search_shapes_response(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(
        return_value={
            "count": 1,
            "buildType": [
                {
                    "id": "Proj_Build",
                    "name": "Build",
                    "projectId": "Proj",
                    "projectName": "Proj",
                    "paused": False,
                    "type": "regular",
                    "webUrl": "https://tc/Proj_Build",
                    "extra": "stripped",
                }
            ],
        }
    )
    tools = extract_tools(build_configs)
    result = await tools["search_build_configs"](mock_ctx, project_id="Proj")
    cfg = result["build_configurations"][0]
    assert cfg["id"] == "Proj_Build"
    assert cfg["project_id"] == "Proj"
    assert "extra" not in cfg


async def test_get_details_extracts_steps_and_triggers(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(
        return_value={
            "id": "Proj_Build",
            "name": "Build",
            "steps": {
                "step": [
                    {
                        "id": "RUNNER_1",
                        "name": "Compile",
                        "type": "simpleRunner",
                        "properties": {"property": [{"name": "script", "value": "make"}]},
                    }
                ]
            },
            "triggers": {"trigger": [{"id": "TRIGGER_1", "type": "vcsTrigger", "properties": {"property": []}}]},
            "parameters": {"property": [{"name": "env", "value": "prod"}]},
            "vcs-root-entries": {
                "vcs-root-entry": [{"id": "e1", "vcs-root": {"id": "r1", "name": "repo", "vcsName": "jetbrains.git"}}]
            },
            "settings": {"property": [{"name": "buildNumberPattern", "value": "%build.counter%"}]},
            "agent-requirements": {"agent-requirement": []},
        }
    )
    tools = extract_tools(build_configs)
    result = await tools["get_build_config_details"](mock_ctx, build_type_id="Proj_Build")

    assert result["step_count"] == 1
    assert result["steps"][0]["properties"] == {"script": "make"}
    assert result["trigger_count"] == 1
    assert result["parameters"] == {"env": "prod"}
    assert result["vcs_roots"][0]["vcs_name"] == "jetbrains.git"


async def test_get_details_not_found(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(side_effect=_http_error(404))
    tools = extract_tools(build_configs)
    result = await tools["get_build_config_details"](mock_ctx, build_type_id="X")
    assert "not found" in result["error"]


async def test_branches_shapes_response(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(
        return_value={
            "count": 2,
            "branch": [
                {"name": "main", "default": True, "active": True},
                {"name": "dev", "default": False, "active": False},
            ],
        }
    )
    tools = extract_tools(build_configs)
    result = await tools["get_build_config_branches"](mock_ctx, build_type_id="Proj_Build")
    assert result["count"] == 2
    assert result["branches"][0]["default"] is True


async def test_api_error_returned_as_dict(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(side_effect=_http_error(500))
    tools = extract_tools(build_configs)
    result = await tools["search_build_configs"](mock_ctx, project_id="Proj")
    assert "TeamCity API error: 500" in result["error"]
