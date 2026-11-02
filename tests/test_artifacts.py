"""Tests for build-artifact tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
from helpers import extract_tools

from mcp_teamcity.tools import artifacts


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://tc.example.com/x")
    response = httpx.Response(status, request=request, text="boom")
    return httpx.HTTPStatusError("err", request=request, response=response)


async def test_list_artifacts_marks_directories(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(
        return_value={
            "file": [
                {"name": "reports", "fullName": "reports", "children": {"href": "/x"}},
                {"name": "build.log", "fullName": "build.log", "size": 1024, "content": {"href": "/y"}},
            ]
        }
    )
    tools = extract_tools(artifacts)
    result = await tools["list_build_artifacts"](mock_ctx, build_id="12345")
    assert result["count"] == 2
    by_name = {a["name"]: a for a in result["artifacts"]}
    assert by_name["reports"]["is_directory"] is True
    assert by_name["build.log"]["is_directory"] is False
    assert by_name["build.log"]["size_bytes"] == 1024


async def test_list_artifacts_not_found(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(side_effect=_http_error(404))
    tools = extract_tools(artifacts)
    result = await tools["list_build_artifacts"](mock_ctx, build_id="0")
    assert "not found" in result["error"]


async def test_artifact_content_returns_text(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(return_value={"name": "junit.xml", "size": 20})
    client.get_text = AsyncMock(return_value="<testsuite>\n  <case/>\n</testsuite>")
    tools = extract_tools(artifacts)
    result = await tools["get_build_artifact_content"](mock_ctx, build_id="12345", path="reports/junit.xml")
    assert result["total_lines"] == 3
    assert "<testsuite>" in result["content"]
    assert result["has_more"] is False


async def test_artifact_content_refuses_large(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(return_value={"name": "big.bin", "size": 99_000_000})
    tools = extract_tools(artifacts)
    result = await tools["get_build_artifact_content"](mock_ctx, build_id="12345", path="big.bin")
    assert "too large" in result["error"]
    # Content download must not have been attempted.
    client.get_text.assert_not_called()


async def test_artifact_content_line_range(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(return_value={"size": 50})
    client.get_text = AsyncMock(return_value="\n".join(f"l{i}" for i in range(10)))
    tools = extract_tools(artifacts)
    result = await tools["get_build_artifact_content"](mock_ctx, build_id="1", path="f.txt", start_line=2, max_lines=3)
    assert result["start_line"] == 2
    assert result["end_line"] == 5
    assert result["content"] == "l2\nl3\nl4"
    assert result["has_more"] is True
    assert result["truncated_lines"] == 0


async def test_artifact_content_truncates_long_lines(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(return_value={"size": 100})
    # One short line, one 5000-char line.
    client.get_text = AsyncMock(return_value="short\n" + ("x" * 5000))
    tools = extract_tools(artifacts)
    result = await tools["get_build_artifact_content"](mock_ctx, build_id="1", path="min.js", max_line_length=100)
    lines = result["content"].split("\n")
    assert lines[0] == "short"
    assert lines[1].startswith("x" * 100)
    assert "[+4900 chars truncated]" in lines[1]
    assert result["truncated_lines"] == 1
    # The returned content is bounded regardless of the source line's length.
    assert len(lines[1]) < 200
