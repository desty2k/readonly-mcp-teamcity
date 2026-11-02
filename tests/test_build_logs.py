"""Tests for build-log tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
from helpers import extract_tools

from mcp_teamcity.tools import build_logs


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://tc.example.com/downloadBuildLog.html")
    response = httpx.Response(status, request=request, text="boom")
    return httpx.HTTPStatusError("err", request=request, response=response)


def _log_text(n: int) -> str:
    return "\n".join(f"line {i}" for i in range(n))


async def test_get_log_first_page(mock_ctx: MagicMock) -> None:
    mock_ctx.lifespan_context.client.get_text = AsyncMock(return_value=_log_text(1000))
    tools = extract_tools(build_logs)
    result = await tools["get_build_log"](mock_ctx, build_id="1", max_lines=100)
    assert result["total_lines"] == 1000
    assert result["lines_returned"] == 100
    assert result["start_line"] == 0
    assert result["end_line"] == 100
    assert result["has_more"] is True
    assert result["log"].startswith("line 0")


async def test_get_log_tail(mock_ctx: MagicMock) -> None:
    mock_ctx.lifespan_context.client.get_text = AsyncMock(return_value=_log_text(1000))
    tools = extract_tools(build_logs)
    result = await tools["get_build_log"](mock_ctx, build_id="1", max_lines=10, tail=True)
    assert result["start_line"] == 990
    assert result["end_line"] == 1000
    assert result["log"].endswith("line 999")


async def test_get_log_range(mock_ctx: MagicMock) -> None:
    mock_ctx.lifespan_context.client.get_text = AsyncMock(return_value=_log_text(1000))
    tools = extract_tools(build_logs)
    result = await tools["get_build_log"](mock_ctx, build_id="1", start_line=10, end_line=20)
    assert result["start_line"] == 10
    assert result["end_line"] == 20
    assert result["lines_returned"] == 10


async def test_get_log_empty(mock_ctx: MagicMock) -> None:
    mock_ctx.lifespan_context.client.get_text = AsyncMock(return_value="")
    tools = extract_tools(build_logs)
    result = await tools["get_build_log"](mock_ctx, build_id="1")
    assert result["total_lines"] == 0
    assert result["has_more"] is False


async def test_get_log_not_found(mock_ctx: MagicMock) -> None:
    mock_ctx.lifespan_context.client.get_text = AsyncMock(side_effect=_http_error(404))
    tools = extract_tools(build_logs)
    result = await tools["get_build_log"](mock_ctx, build_id="0")
    assert "not found" in result["error"]


async def test_search_log_finds_matches_with_context(mock_ctx: MagicMock) -> None:
    log = "start\nERROR: boom\nmiddle\nERROR: again\nend"
    mock_ctx.lifespan_context.client.get_text = AsyncMock(return_value=log)
    tools = extract_tools(build_logs)
    result = await tools["search_build_log"](mock_ctx, build_id="1", query="error", context_lines=1)
    assert result["total_matches"] == 2
    assert result["matches"][0]["line_number"] == 1
    # Context includes the surrounding line and flags the match.
    match_line = [c for c in result["matches"][0]["context"] if c["is_match"]][0]
    assert match_line["text"] == "ERROR: boom"


async def test_search_log_truncates(mock_ctx: MagicMock) -> None:
    log = "\n".join("match" for _ in range(50))
    mock_ctx.lifespan_context.client.get_text = AsyncMock(return_value=log)
    tools = extract_tools(build_logs)
    result = await tools["search_build_log"](mock_ctx, build_id="1", query="match", max_matches=10)
    assert result["total_matches"] == 50
    assert result["matches_returned"] == 10
    assert result["truncated"] is True


async def test_get_log_range_is_capped_by_max_lines(mock_ctx: MagicMock) -> None:
    mock_ctx.lifespan_context.client.get_text = AsyncMock(return_value=_log_text(20000))
    tools = extract_tools(build_logs)
    result = await tools["get_build_log"](mock_ctx, build_id="1", start_line=0, end_line=15000, max_lines=100)
    assert result["lines_returned"] == 100
    assert result["end_line"] == 100
    assert result["has_more"] is True


async def test_get_log_range_cannot_exceed_hard_cap(mock_ctx: MagicMock) -> None:
    mock_ctx.lifespan_context.client.get_text = AsyncMock(return_value=_log_text(20000))
    tools = extract_tools(build_logs)
    result = await tools["get_build_log"](mock_ctx, build_id="1", start_line=0, end_line=20000, max_lines=10**6)
    assert result["lines_returned"] == 5000


async def test_get_log_reports_running_build(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(return_value={"state": "running"})
    client.get_text = AsyncMock(return_value=_log_text(10))
    tools = extract_tools(build_logs)
    result = await tools["get_build_log"](mock_ctx, build_id="1", tail=True, max_lines=5)
    assert result["build_finished"] is False
