"""Tests for the resolve_teamcity_url tool."""

from __future__ import annotations

from unittest.mock import MagicMock

from helpers import extract_tools

from mcp_teamcity.tools import url_resolve


async def test_resolves_build_url(mock_ctx: MagicMock) -> None:
    tools = extract_tools(url_resolve)
    result = await tools["resolve_teamcity_url"](
        mock_ctx, url="https://tc.example.com/buildConfiguration/Proj_Build/12345"
    )
    assert result["url_type"] == "build"
    assert result["build_type_id"] == "Proj_Build"
    assert result["build_id"] == "12345"


async def test_resolves_project_url(mock_ctx: MagicMock) -> None:
    tools = extract_tools(url_resolve)
    result = await tools["resolve_teamcity_url"](mock_ctx, url="https://tc.example.com/project/MyProject")
    assert result["url_type"] == "project"
    assert result["project_id"] == "MyProject"


async def test_empty_url_errors(mock_ctx: MagicMock) -> None:
    tools = extract_tools(url_resolve)
    result = await tools["resolve_teamcity_url"](mock_ctx, url="  ")
    assert "error" in result


async def test_unknown_url_errors(mock_ctx: MagicMock) -> None:
    tools = extract_tools(url_resolve)
    result = await tools["resolve_teamcity_url"](mock_ctx, url="https://tc.example.com/unknown/path")
    assert "error" in result
    assert result["url"] == "https://tc.example.com/unknown/path"
