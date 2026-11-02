"""Tests for the fuzzy find_build_config tool."""

from __future__ import annotations

from unittest.mock import MagicMock

from helpers import extract_tools

from mcp_teamcity.index import BuildConfigEntry
from mcp_teamcity.tools import find_config


def _load_index(mock_ctx: MagicMock, entries: list[BuildConfigEntry]) -> None:
    index = mock_ctx.lifespan_context.build_config_index
    index._entries = entries
    index._search_texts = [e.search_text for e in entries]
    index._loaded = True


def _entry(bt_id: str, name: str, project_name: str) -> BuildConfigEntry:
    return BuildConfigEntry(
        build_type_id=bt_id,
        name=name,
        project_id="Proj",
        project_name=project_name,
        description=None,
        web_url=f"https://tc/{bt_id}",
        search_text=f"{project_name} {name}".lower(),
    )


async def test_empty_query_errors(mock_ctx: MagicMock) -> None:
    _load_index(mock_ctx, [])
    tools = extract_tools(find_config)
    result = await tools["find_build_config"](mock_ctx, query="   ")
    assert "error" in result


async def test_index_not_loaded_errors(mock_ctx: MagicMock) -> None:
    # Default index in the fixture is not loaded.
    tools = extract_tools(find_config)
    result = await tools["find_build_config"](mock_ctx, query="deploy")
    assert "not yet loaded" in result["error"]


async def test_returns_ranked_results(mock_ctx: MagicMock) -> None:
    _load_index(
        mock_ctx,
        [
            _entry("Payments_DeployProd", "Deploy Prod", "Payments / API"),
            _entry("Billing_Nightly", "Nightly Test", "Billing"),
        ],
    )
    tools = extract_tools(find_config)
    result = await tools["find_build_config"](mock_ctx, query="deploy api prod", limit=5)
    assert result["count"] >= 1
    assert result["results"][0]["id"] == "Payments_DeployProd"
    assert result["total_configs"] == 2
    assert result["query"] == "deploy api prod"


async def test_index_load_error_is_reported(mock_ctx: MagicMock) -> None:
    mock_ctx.lifespan_context.build_config_index.last_error = "TeamCity rejected the access token (HTTP 401)."
    tools = extract_tools(find_config)
    result = await tools["find_build_config"](mock_ctx, query="deploy")
    assert result["error"] == "Build-configuration index failed to load"
    assert "401" in result["reason"]


async def test_ambiguous_results_are_flagged(mock_ctx: MagicMock) -> None:
    _load_index(
        mock_ctx,
        [
            _entry("A_Unit", "auth-service unit tests", "Identity"),
            _entry("A_Integration", "auth-service integration tests", "Identity"),
        ],
    )
    tools = extract_tools(find_config)
    result = await tools["find_build_config"](mock_ctx, query="auth-service tests")
    assert result["ambiguous"] is True
