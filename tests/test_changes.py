"""Tests for VCS-change tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
from helpers import extract_tools

from mcp_teamcity.tools import changes


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://tc.example.com/x")
    response = httpx.Response(status, request=request, text="boom")
    return httpx.HTTPStatusError("err", request=request, response=response)


async def test_search_requires_filter(mock_ctx: MagicMock) -> None:
    tools = extract_tools(changes)
    result = await tools["search_changes"](mock_ctx)
    assert "error" in result
    mock_ctx.lifespan_context.client.get.assert_not_called()


async def test_search_shapes_response(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(
        return_value={
            "count": 1,
            "change": [
                {
                    "id": 42,
                    "version": "abc123def",
                    "username": "alice",
                    "date": "20240101T000000+0000",
                    "comment": "fix bug",
                    "files": {"count": 3},
                }
            ],
        }
    )
    tools = extract_tools(changes)
    result = await tools["search_changes"](mock_ctx, build_id="99")
    c = result["changes"][0]
    assert c["version"] == "abc123def"
    assert c["file_count"] == 3


async def test_details_extracts_files(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(
        return_value={
            "id": 42,
            "version": "abc123",
            "username": "alice",
            "comment": "fix",
            "vcsRootInstance": {"name": "repo", "vcs-root": {"id": "r1", "name": "repo"}},
            "files": {
                "file": [
                    {"file": "src/a.py", "changeType": "edited"},
                    {"relativePath": "src/b.py", "changeType": "added"},
                ]
            },
        }
    )
    tools = extract_tools(changes)
    result = await tools["get_change_details"](mock_ctx, change_id="42")
    assert result["file_count"] == 2
    assert result["files"][0]["path"] == "src/a.py"
    assert result["files"][1]["path"] == "src/b.py"
    assert result["vcs_root_name"] == "repo"


async def test_details_not_found(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(side_effect=_http_error(404))
    tools = extract_tools(changes)
    result = await tools["get_change_details"](mock_ctx, change_id="0")
    assert "not found" in result["error"]


async def test_search_uses_since_change_not_since_date(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(return_value={"count": 0, "change": []})
    tools = extract_tools(changes)
    await tools["search_changes"](mock_ctx, build_type_id="Proj_Build", since_change="abc123")
    locator = client.get.await_args.kwargs["params"]["locator"]
    assert "sinceChange:(version:abc123)" in locator
    # The invalid ChangeLocator date dimension must never be emitted.
    assert "sinceDate" not in locator


async def test_search_since_change_numeric_id(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(return_value={"count": 0, "change": []})
    tools = extract_tools(changes)
    await tools["search_changes"](mock_ctx, build_type_id="Proj_Build", since_change="42")
    assert "sinceChange:42" in client.get.await_args.kwargs["params"]["locator"]


async def test_unknown_since_change_explains_full_sha(mock_ctx: MagicMock) -> None:
    import httpx

    request = httpx.Request("GET", "https://tc.example.com/app/rest/changes")
    error = httpx.HTTPStatusError("err", request=request, response=httpx.Response(404, request=request))
    mock_ctx.lifespan_context.client.get = AsyncMock(side_effect=error)
    result = await extract_tools(changes)["search_changes"](mock_ctx, build_type_id="P_B", since_change="a727be0")
    assert "full commit SHA" in result["reason"]
