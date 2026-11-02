"""Tests for build-queue tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from helpers import extract_tools

from mcp_teamcity.tools import queue


async def test_queue_shapes_response(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(
        return_value={
            "count": 1,
            "build": [
                {
                    "id": 555,
                    "state": "queued",
                    "branchName": "main",
                    "waitReason": "Waiting for an agent",
                    "buildType": {"id": "Proj_Build", "name": "Build", "projectId": "Proj", "projectName": "Proj"},
                    "triggered": {"type": "vcs", "user": {"username": "ci"}},
                    "compatibleAgents": {"count": 3},
                }
            ],
        }
    )
    tools = extract_tools(queue)
    result = await tools["get_build_queue"](mock_ctx)
    b = result["queued_builds"][0]
    assert b["id"] == 555
    assert b["wait_reason"] == "Waiting for an agent"
    assert b["compatible_agent_count"] == 3
    assert b["build_type_name"] == "Build"


async def test_queue_empty(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(return_value={"count": 0, "build": []})
    tools = extract_tools(queue)
    result = await tools["get_build_queue"](mock_ctx)
    assert result["queued_builds"] == []
    assert result["count"] == 0
