"""Build-queue tools — inspect builds waiting for an agent."""

from __future__ import annotations

import logging
from typing import Annotated, Any

import httpx
from fastmcp import Context, FastMCP
from pydantic import Field

from mcp_teamcity import validation as v
from mcp_teamcity.errors import api_error, connection_error
from mcp_teamcity.pagination import build_pagination, clamp_limit

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def get_build_queue(
        ctx: Context,
        project_id: Annotated[str | None, "Filter queued builds by project ID."] = None,
        build_type_id: Annotated[str | None, "Filter queued builds by build configuration ID."] = None,
        page: Annotated[int, Field(description="Page number, 1-indexed", ge=1)] = 1,
        limit: Annotated[int, Field(description="Max results per page", ge=1, le=500)] = 50,
    ) -> dict[str, Any]:
        """List builds currently in the TeamCity build queue.

        Shows builds waiting to be assigned to an agent: queue entry, branch,
        triggered-by, wait reason, and compatible-agent count.

        Returns:
            List of queued builds with id, build type, branch, triggered-by,
            wait_reason, and compatible_agent_count.

        Example questions:
            - "What's in the build queue?"
            - "How many builds are waiting for agents?"
            - "Is the deploy build queued?"
        """
        try:
            project_id = v.external_id(project_id, "project_id") if project_id else None
            build_type_id = v.external_id(build_type_id, "build_type_id") if build_type_id else None
        except v.InvalidArgument as exc:
            return v.invalid(exc)

        app = ctx.lifespan_context
        client = app.client
        limit = clamp_limit(limit, app.settings.default_limit, app.settings.max_limit)
        page = max(1, page)
        offset = (page - 1) * limit

        try:
            locator_parts: list[str] = []
            if project_id:
                locator_parts.append(f"project:(id:{project_id})")
            if build_type_id:
                locator_parts.append(f"buildType:(id:{build_type_id})")
            locator_parts.append(f"count:{limit}")
            locator_parts.append(f"start:{offset}")

            params: dict[str, Any] = {
                "locator": ",".join(locator_parts),
                "fields": (
                    "count,nextHref,prevHref,build(id,number,state,branchName,defaultBranch,"
                    "queuedDate,waitReason,personal,webUrl,"
                    "buildType(id,name,projectId,projectName),"
                    "triggered(type,user(username,name)),"
                    "compatibleAgents(count))"
                ),
            }

            data = await client.get("/app/rest/buildQueue", params=params)
            queued = data.get("build", []) if isinstance(data, dict) else []

            results = []
            for b in queued:
                build_type = b.get("buildType", {}) or {}
                triggered = b.get("triggered", {}) or {}
                triggered_user = triggered.get("user", {}) or {}
                compat_agents = b.get("compatibleAgents", {}) or {}
                results.append(
                    {
                        "id": b.get("id"),
                        "number": b.get("number"),
                        "state": b.get("state"),
                        "branch_name": b.get("branchName"),
                        "default_branch": b.get("defaultBranch", False),
                        "personal": b.get("personal", False),
                        "queued_date": b.get("queuedDate"),
                        "wait_reason": b.get("waitReason"),
                        "web_url": b.get("webUrl"),
                        "build_type_id": build_type.get("id"),
                        "build_type_name": build_type.get("name"),
                        "project_id": build_type.get("projectId"),
                        "project_name": build_type.get("projectName"),
                        "triggered_by": triggered.get("type"),
                        "triggered_by_user": triggered_user.get("username"),
                        "compatible_agent_count": compat_agents.get("count"),
                    }
                )

            logger.info(
                "get_build_queue project_id=%s build_type_id=%s count=%d", project_id, build_type_id, len(results)
            )
            return {
                "queued_builds": results,
                "count": len(results),
                "pagination": build_pagination(page, limit, data),
            }

        except httpx.HTTPStatusError as exc:
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)
