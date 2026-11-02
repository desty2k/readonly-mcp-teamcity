"""Build-agent tools — inspect agents and agent pools."""

from __future__ import annotations

import logging
from typing import Annotated, Any

import httpx
from fastmcp import Context, FastMCP
from pydantic import Field

from mcp_teamcity.errors import api_error, connection_error, not_found
from mcp_teamcity.pagination import build_pagination, clamp_limit

logger = logging.getLogger(__name__)

# Agents report their OS as teamcity.agent.jvm.os.name; there is no
# teamcity.agent.os.name property (checked against TeamCity 2026.2).
_OS_PROPERTIES = ("teamcity.agent.jvm.os.name", "teamcity.agent.os.name")


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def search_agents(
        ctx: Context,
        pool_id: Annotated[int | None, "Filter by agent pool ID."] = None,
        connected: Annotated[
            bool | None,
            "Filter by connection state. True = connected, False = disconnected.",
        ] = None,
        authorized: Annotated[
            bool | None,
            "Filter by authorization state. Unauthorized agents cannot run builds.",
        ] = None,
        enabled: Annotated[
            bool | None,
            "Filter by enabled state. Disabled agents are excluded from build assignment.",
        ] = None,
        page: Annotated[int, Field(description="Page number, 1-indexed", ge=1)] = 1,
        limit: Annotated[int, Field(description="Max results per page", ge=1, le=500)] = 50,
    ) -> dict[str, Any]:
        """Search TeamCity build agents.

        Build agents are machines that execute builds. Each belongs to an agent
        pool and reports capability properties (OS, installed software, etc.).

        Returns:
            List of agents with id, name, connected/authorized/enabled status,
            pool info, IP, OS, and current build (if running one).

        Example questions:
            - "How many agents are connected?"
            - "Which agents are offline?"
            - "What agents are in the Linux pool?"
            - "Are any agents currently running builds?"
        """
        app = ctx.lifespan_context
        client = app.client
        limit = clamp_limit(limit, app.settings.default_limit, app.settings.max_limit)
        page = max(1, page)
        offset = (page - 1) * limit

        try:
            locator_parts: list[str] = []
            if pool_id is not None:
                locator_parts.append(f"pool:(id:{pool_id})")
            if connected is not None:
                locator_parts.append(f"connected:{str(connected).lower()}")
            if authorized is not None:
                locator_parts.append(f"authorized:{str(authorized).lower()}")
            if enabled is not None:
                locator_parts.append(f"enabled:{str(enabled).lower()}")
            locator_parts.append(f"count:{limit}")
            locator_parts.append(f"start:{offset}")

            params: dict[str, Any] = {
                "locator": ",".join(locator_parts),
                "fields": (
                    "count,nextHref,prevHref,agent(id,name,typeId,connected,authorized,"
                    "enabled,uptodate,ip,pool(id,name),"
                    "build(id,number,status,buildType(id,name)),"
                    "properties(property(name,value)))"
                ),
            }

            data = await client.get("/app/rest/agents", params=params)
            agents_list = data.get("agent", []) if isinstance(data, dict) else []

            results = []
            for a in agents_list:
                pool = a.get("pool", {}) or {}
                current_build = a.get("build", {}) or {}
                current_bt = current_build.get("buildType", {}) or {}

                os_name = None
                props = a.get("properties", {})
                if isinstance(props, dict):
                    for prop in props.get("property", []):
                        if prop.get("name") in _OS_PROPERTIES:
                            os_name = prop.get("value")
                            break

                has_build = current_build.get("id") is not None
                results.append(
                    {
                        "id": a.get("id"),
                        "name": a.get("name"),
                        "type_id": a.get("typeId"),
                        "connected": a.get("connected", False),
                        "authorized": a.get("authorized", False),
                        "enabled": a.get("enabled", False),
                        "up_to_date": a.get("uptodate", True),
                        "ip": a.get("ip"),
                        "os_name": os_name,
                        "pool_id": pool.get("id"),
                        "pool_name": pool.get("name"),
                        "current_build_id": (current_build.get("id") if has_build else None),
                        "current_build_number": (current_build.get("number") if has_build else None),
                        "current_build_type": (current_bt.get("name") if has_build else None),
                    }
                )

            logger.info("search_agents pool_id=%s count=%d", pool_id, len(results))
            return {
                "agents": results,
                "count": len(results),
                "pagination": build_pagination(page, limit, data),
            }

        except httpx.HTTPStatusError as exc:
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)

    @mcp.tool()
    async def list_agent_pools(
        ctx: Context,
        page: Annotated[int, Field(description="Page number, 1-indexed", ge=1)] = 1,
        limit: Annotated[int, Field(description="Max results per page", ge=1, le=500)] = 50,
    ) -> dict[str, Any]:
        """List TeamCity agent pools.

        Agent pools group build agents for resource management. Each pool has a
        set of assigned projects and agent-count limits.

        Returns:
            List of agent pools with id, name, max_agents, agent_count, and
            project_count.

        Example questions:
            - "What agent pools do we have?"
            - "How many agents are in each pool?"
        """
        app = ctx.lifespan_context
        client = app.client
        limit = clamp_limit(limit, app.settings.default_limit, app.settings.max_limit)
        page = max(1, page)
        offset = (page - 1) * limit

        try:
            params: dict[str, Any] = {
                "locator": f"count:{limit},start:{offset}",
                "fields": "count,nextHref,prevHref,agentPool(id,name,maxAgents,agents(count),projects(count))",
            }

            data = await client.get("/app/rest/agentPools", params=params)
            pools_list = data.get("agentPool", []) if isinstance(data, dict) else []

            results = []
            for pool in pools_list:
                agents_data = pool.get("agents", {}) or {}
                projects_data = pool.get("projects", {}) or {}
                results.append(
                    {
                        "id": pool.get("id"),
                        "name": pool.get("name"),
                        "max_agents": pool.get("maxAgents"),
                        "agent_count": (agents_data.get("count", 0) if isinstance(agents_data, dict) else 0),
                        "project_count": (projects_data.get("count", 0) if isinstance(projects_data, dict) else 0),
                    }
                )

            logger.info("list_agent_pools count=%d", len(results))
            return {
                "agent_pools": results,
                "count": len(results),
                "pagination": build_pagination(page, limit, data),
            }

        except httpx.HTTPStatusError as exc:
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)

    @mcp.tool()
    async def get_agent_details(
        ctx: Context,
        agent_id: Annotated[int, "Agent ID"],
    ) -> dict[str, Any]:
        """Get detailed status for a single build agent.

        Surfaces WHY an agent may not be taking builds: the enabled/authorized
        state with their human comments, last activity, version, pool, current
        build, and an OS summary. The first thing to check when builds sit queued
        or an agent looks idle.

        Returns:
            Agent details including connected/authorized/enabled state and
            comments, last_activity, version, pool, current build, and OS info.

        Example questions:
            - "Why isn't agent 7 running builds?"
            - "Is this agent enabled and authorized?"
            - "When was this agent last active?"
        """
        app = ctx.lifespan_context
        client = app.client

        try:
            params = {
                "fields": (
                    "id,name,typeId,connected,authorized,enabled,uptodate,ip,version,lastActivityTime,"
                    "enabledInfo(comment(text)),authorizedInfo(comment(text)),"
                    "pool(id,name),"
                    "build(id,number,status,buildType(id,name)),"
                    "properties(count,property(name,value))"
                ),
            }
            data = await client.get(f"/app/rest/agents/id:{agent_id}", params=params)
            if not isinstance(data, dict):
                return {"error": f"Unexpected response for agent '{agent_id}'"}

            pool = data.get("pool", {}) or {}
            current_build = data.get("build", {}) or {}
            current_bt = current_build.get("buildType", {}) or {}
            enabled_info = data.get("enabledInfo", {}) or {}
            authorized_info = data.get("authorizedInfo", {}) or {}

            os_name = None
            props = data.get("properties", {})
            property_count = props.get("count") if isinstance(props, dict) else None
            if isinstance(props, dict):
                for prop in props.get("property", []):
                    if prop.get("name") in _OS_PROPERTIES:
                        os_name = prop.get("value")
                        break

            has_build = current_build.get("id") is not None
            logger.info("get_agent_details agent_id=%s connected=%s", agent_id, data.get("connected"))
            return {
                "id": data.get("id"),
                "name": data.get("name"),
                "type_id": data.get("typeId"),
                "connected": data.get("connected", False),
                "authorized": data.get("authorized", False),
                "authorized_comment": (authorized_info.get("comment", {}) or {}).get("text"),
                "enabled": data.get("enabled", False),
                "enabled_comment": (enabled_info.get("comment", {}) or {}).get("text"),
                "up_to_date": data.get("uptodate", True),
                "ip": data.get("ip"),
                "version": data.get("version"),
                "last_activity": data.get("lastActivityTime"),
                "os_name": os_name,
                "property_count": property_count,
                "pool_id": pool.get("id"),
                "pool_name": pool.get("name"),
                "current_build_id": (current_build.get("id") if has_build else None),
                "current_build_number": (current_build.get("number") if has_build else None),
                "current_build_type": (current_bt.get("name") if has_build else None),
            }

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return not_found("Agent", str(agent_id))
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)
