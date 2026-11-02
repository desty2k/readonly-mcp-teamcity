"""Tests for server assembly: tool registration and instructions."""

from __future__ import annotations

from helpers import extract_tools

from mcp_teamcity import __version__
from mcp_teamcity.server import MCP_INSTRUCTIONS, create_server
from mcp_teamcity.settings import TeamCitySettings
from mcp_teamcity.tools import (
    agents,
    artifacts,
    build_configs,
    build_logs,
    builds,
    changes,
    diagnose,
    find_config,
    problems,
    projects,
    queue,
    server_info,
    tests,
    url_resolve,
)

_EXPECTED_TOOLS = {
    "search_projects",
    "get_project_details",
    "search_build_configs",
    "get_build_config_details",
    "get_build_config_branches",
    "search_builds",
    "get_build_details",
    "get_build_statistics",
    "get_build_chain",
    "get_build_log",
    "search_build_log",
    "get_build_test_results",
    "get_test_details",
    "get_build_problems",
    "search_investigations",
    "list_muted_tests",
    "get_build_queue",
    "search_agents",
    "list_agent_pools",
    "get_agent_details",
    "search_changes",
    "get_change_details",
    "list_build_artifacts",
    "get_build_artifact_content",
    "find_build_config",
    "resolve_teamcity_url",
    "get_server_info",
    "get_server_health",
    "diagnose_build",
}


def test_all_tools_registered() -> None:
    names: set[str] = set()
    for module in [
        projects,
        build_configs,
        builds,
        build_logs,
        tests,
        problems,
        queue,
        agents,
        changes,
        artifacts,
        diagnose,
        find_config,
        url_resolve,
        server_info,
    ]:
        names |= set(extract_tools(module))
    assert names == _EXPECTED_TOOLS
    assert len(_EXPECTED_TOOLS) == 29


def test_create_server_builds() -> None:
    settings = TeamCitySettings(base_url="https://tc.test", token="t")
    mcp = create_server(settings)
    assert mcp is not None


def test_instructions_state_read_only() -> None:
    lowered = MCP_INSTRUCTIONS.lower()
    assert "read-only" in lowered
    assert "cannot" in lowered


async def test_every_tool_is_annotated_read_only() -> None:
    mcp = create_server(TeamCitySettings(base_url="https://tc.test", token="t"))
    tools = await mcp.list_tools()
    assert len(tools) == 29
    for tool in tools:
        assert tool.annotations is not None, tool.name
        assert tool.annotations.readOnlyHint is True, tool.name
        assert tool.annotations.destructiveHint is False, tool.name


def test_server_reports_package_version() -> None:
    server = create_server(TeamCitySettings(base_url="https://tc.example.com", token="t"))
    assert server.version == __version__
