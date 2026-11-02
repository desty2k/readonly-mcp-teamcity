"""Tests for build tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
from helpers import extract_tools

from mcp_teamcity.tools import builds
from mcp_teamcity.tools.builds import _build_locator


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://tc.example.com/x")
    response = httpx.Response(status, request=request, text="boom")
    return httpx.HTTPStatusError("err", request=request, response=response)


def test_build_locator_default_branch() -> None:
    locator = _build_locator(build_type_id="X", branch="<default>", count=10, start=0)
    assert "branch:(default:true)" in locator
    assert "buildType:(id:X)" in locator
    assert "count:10" in locator


def test_build_locator_named_branch_and_status() -> None:
    locator = _build_locator(status="failure", branch="release/2.0")
    assert "status:FAILURE" in locator
    assert "branch:(name:(value:release/2.0,matchType:equals))" in locator


async def test_search_requires_filter(mock_ctx: MagicMock) -> None:
    tools = extract_tools(builds)
    result = await tools["search_builds"](mock_ctx)
    assert "error" in result
    mock_ctx.lifespan_context.client.get.assert_not_called()


async def test_search_shapes_response(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(
        return_value={
            "count": 1,
            "build": [
                {
                    "id": 12345,
                    "number": "1.2.3",
                    "status": "SUCCESS",
                    "state": "finished",
                    "branchName": "main",
                    "buildType": {"id": "Proj_Build", "name": "Build", "projectId": "Proj"},
                    "triggered": {"type": "user", "user": {"username": "alice"}},
                }
            ],
        }
    )
    tools = extract_tools(builds)
    result = await tools["search_builds"](mock_ctx, build_type_id="Proj_Build")
    b = result["builds"][0]
    assert b["id"] == 12345
    assert b["build_type_name"] == "Build"
    assert b["triggered_by_user"] == "alice"


async def test_get_details_extracts_nested(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(
        return_value={
            "id": 12345,
            "number": "1.2.3",
            "status": "FAILURE",
            "buildType": {"id": "Proj_Build", "name": "Build", "projectId": "Proj"},
            "agent": {"id": 7, "name": "agent-7", "typeId": 7},
            "revisions": {
                "revision": [{"version": "abc123", "vcs-root-instance": {"name": "repo", "vcs-root": {"id": "r1"}}}]
            },
            "properties": {"property": [{"name": "env", "value": "prod"}]},
            "statistics": {"property": [{"name": "BuildDuration", "value": "5000"}]},
            "snapshot-dependencies": {"build": [{"id": 1, "number": "9", "buildType": {"id": "Dep"}}]},
            "tags": {"tag": [{"name": "release"}]},
        }
    )
    tools = extract_tools(builds)
    result = await tools["get_build_details"](mock_ctx, build_id="12345")
    assert result["status"] == "FAILURE"
    assert result["agent"]["name"] == "agent-7"
    assert result["revisions"][0]["version"] == "abc123"
    assert result["parameters"] == {"env": "prod"}
    assert result["statistics"] == {"BuildDuration": "5000"}
    assert result["snapshot_dependencies"][0]["build_id"] == 1
    assert result["tags"] == ["release"]


async def test_get_details_not_found(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(side_effect=_http_error(404))
    tools = extract_tools(builds)
    result = await tools["get_build_details"](mock_ctx, build_id="0")
    assert "not found" in result["error"]


async def test_get_statistics(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(return_value={"property": [{"name": "BuildDuration", "value": "5000"}]})
    tools = extract_tools(builds)
    result = await tools["get_build_statistics"](mock_ctx, build_id="12345")
    assert result["statistics"] == {"BuildDuration": "5000"}


def test_build_locator_uses_modern_date_dimensions() -> None:
    locator = _build_locator(since_date="20240101T000000+0000", until_date="20240201T000000+0000")
    assert "startDate:(date:20240101T000000+0000,condition:after)" in locator
    assert "finishDate:(date:20240201T000000+0000,condition:before)" in locator
    # Legacy forms must be gone.
    assert "sinceDate:" not in locator
    assert "untilDate:" not in locator


async def test_get_details_includes_test_summary(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(
        return_value={
            "id": 12345,
            "status": "FAILURE",
            "testOccurrences": {"count": 100, "passed": 90, "failed": 8, "ignored": 2, "muted": 1, "newFailed": 3},
        }
    )
    tools = extract_tools(builds)
    result = await tools["get_build_details"](mock_ctx, build_id="12345")
    assert result["test_summary"] == {
        "total": 100,
        "passed": 90,
        "failed": 8,
        "ignored": 2,
        "muted": 1,
        "new_failed": 3,
    }


async def test_get_build_chain_both_directions(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(
        side_effect=[
            {"build": [{"id": 1, "number": "u1", "buildType": {"id": "Up", "name": "Upstream"}}]},
            {"build": [{"id": 2, "number": "d1", "buildType": {"id": "Down", "name": "Downstream"}}]},
        ]
    )
    tools = extract_tools(builds)
    result = await tools["get_build_chain"](mock_ctx, build_id="100", direction="both")
    assert result["depends_on"][0]["id"] == 1
    assert result["dependents"][0]["id"] == 2
    assert client.get.await_count == 2


async def test_get_build_chain_upstream_only(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(return_value={"build": []})
    tools = extract_tools(builds)
    result = await tools["get_build_chain"](mock_ctx, build_id="100", direction="upstream")
    assert "depends_on" in result
    assert "dependents" not in result
    client.get.assert_awaited_once()


def test_build_locator_includes_all_branches_by_default() -> None:
    # TeamCity returns only default-branch builds when the locator has no
    # branch dimension; omitting `branch` must mean "all branches".
    assert "branch:(default:any)" in _build_locator(project_id="P")
    assert "branch:(default:true)" in _build_locator(project_id="P", branch="<default>")
    assert "default:any" not in _build_locator(project_id="P", branch="main")
