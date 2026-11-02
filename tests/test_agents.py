"""Tests for agent tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from helpers import extract_tools

from mcp_teamcity.tools import agents


async def test_search_agents_extracts_os_and_build(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(
        return_value={
            "count": 1,
            "agent": [
                {
                    "id": 7,
                    "name": "agent-7",
                    "connected": True,
                    "authorized": True,
                    "enabled": True,
                    "ip": "10.0.0.7",
                    "pool": {"id": 0, "name": "Default"},
                    "build": {"id": 99, "number": "1.0", "buildType": {"id": "B", "name": "Build"}},
                    "properties": {"property": [{"name": "teamcity.agent.jvm.os.name", "value": "Linux"}]},
                }
            ],
        }
    )
    tools = extract_tools(agents)
    result = await tools["search_agents"](mock_ctx, connected=True)
    a = result["agents"][0]
    assert a["os_name"] == "Linux"
    assert a["pool_name"] == "Default"
    assert a["current_build_id"] == 99
    assert a["current_build_type"] == "Build"


async def test_search_agents_idle(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(
        return_value={
            "count": 1,
            "agent": [{"id": 8, "name": "agent-8", "connected": False, "properties": {"property": []}}],
        }
    )
    tools = extract_tools(agents)
    result = await tools["search_agents"](mock_ctx)
    a = result["agents"][0]
    assert a["current_build_id"] is None
    assert a["os_name"] is None


async def test_list_pools_shapes_response(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(
        return_value={
            "count": 1,
            "agentPool": [
                {"id": 0, "name": "Default", "maxAgents": 10, "agents": {"count": 5}, "projects": {"count": 3}}
            ],
        }
    )
    tools = extract_tools(agents)
    result = await tools["list_agent_pools"](mock_ctx)
    pool = result["agent_pools"][0]
    assert pool["name"] == "Default"
    assert pool["agent_count"] == 5
    assert pool["project_count"] == 3


async def test_get_agent_details_surfaces_state_comments(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(
        return_value={
            "id": 7,
            "name": "agent-7",
            "connected": True,
            "authorized": True,
            "enabled": False,
            "enabledInfo": {"comment": {"text": "disabled for maintenance"}},
            "authorizedInfo": {"comment": {"text": "ok"}},
            "pool": {"id": 0, "name": "Default"},
            "lastActivityTime": "20240601T120000+0000",
            "properties": {"count": 42, "property": [{"name": "teamcity.agent.jvm.os.name", "value": "Linux"}]},
        }
    )
    tools = extract_tools(agents)
    result = await tools["get_agent_details"](mock_ctx, agent_id=7)
    assert result["enabled"] is False
    assert result["enabled_comment"] == "disabled for maintenance"
    assert result["authorized_comment"] == "ok"
    assert result["os_name"] == "Linux"
    assert result["property_count"] == 42
    assert result["last_activity"] == "20240601T120000+0000"
