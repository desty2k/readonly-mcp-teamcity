"""Project tools — browse and search the TeamCity project hierarchy."""

from __future__ import annotations

import logging
from typing import Annotated, Any

import httpx
from fastmcp import Context, FastMCP
from pydantic import Field

from mcp_teamcity import validation as v
from mcp_teamcity.errors import api_error, connection_error, not_found
from mcp_teamcity.pagination import build_pagination, clamp_limit

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def search_projects(
        ctx: Context,
        name: Annotated[str | None, "Filter by project name (case-insensitive exact match)"] = None,
        project_id: Annotated[
            str | None,
            "Filter by exact project ID (e.g., 'MyProject'). Use this when you know "
            "the project's technical identifier.",
        ] = None,
        parent_project_id: Annotated[
            str | None,
            "Filter to direct children of this parent project ID. Use '_Root' for top-level projects.",
        ] = None,
        archived: Annotated[bool, "Include archived projects"] = False,
        page: Annotated[int, Field(description="Page number, 1-indexed", ge=1)] = 1,
        limit: Annotated[int, Field(description="Max results per page", ge=1, le=500)] = 50,
    ) -> dict[str, Any]:
        """Search TeamCity projects by name, ID, or parent.

        This is the PRIMARY tool for browsing the TeamCity project hierarchy.
        Projects are organizational containers that hold build configurations
        (jobs). Projects can be nested — use parent_project_id to navigate the
        tree. The root project '_Root' is the parent of all top-level projects.

        Returns:
            List of projects with id, name, description, parent_project_id,
            archived status, and child build-config / project counts.

        Example questions:
            - "What projects do we have in TeamCity?"
            - "Show me all projects under the Platform team"
            - "List top-level projects"
            - "Find the project for the payments service"
        """
        try:
            project_id = v.external_id(project_id, "project_id") if project_id else None
            parent_project_id = v.external_id(parent_project_id, "parent_project_id") if parent_project_id else None
        except v.InvalidArgument as exc:
            return v.invalid(exc)

        app = ctx.lifespan_context
        client = app.client
        limit = clamp_limit(limit, app.settings.default_limit, app.settings.max_limit)
        page = max(1, page)

        try:
            locator_parts: list[str] = []
            if project_id:
                locator_parts.append(f"id:{project_id}")
            if parent_project_id:
                locator_parts.append(f"parentProject:(id:{parent_project_id})")
            if not archived:
                locator_parts.append("archived:false")
            if name:
                locator_parts.append(f"name:{v.locator_value(name)}")

            offset = (page - 1) * limit
            locator_parts.append(f"count:{limit}")
            locator_parts.append(f"start:{offset}")

            params: dict[str, Any] = {
                "locator": ",".join(locator_parts),
                "fields": (
                    "count,nextHref,prevHref,project(id,name,description,archived,parentProjectId,"
                    "buildTypes(count),projects(count))"
                ),
            }

            data = await client.get("/app/rest/projects", params=params)
            projects = data.get("project", []) if isinstance(data, dict) else []

            results = []
            for p in projects:
                bt_data = p.get("buildTypes")
                cp_data = p.get("projects")
                results.append(
                    {
                        "id": p.get("id"),
                        "name": p.get("name"),
                        "description": p.get("description"),
                        "archived": p.get("archived", False),
                        "parent_project_id": p.get("parentProjectId"),
                        "build_config_count": (bt_data.get("count", 0) if isinstance(bt_data, dict) else 0),
                        "child_project_count": (cp_data.get("count", 0) if isinstance(cp_data, dict) else 0),
                    }
                )

            logger.debug("search_projects name=%s project_id=%s count=%d", name, project_id, len(results))
            return {
                "projects": results,
                "count": len(results),
                "pagination": build_pagination(page, limit, data),
            }

        except httpx.HTTPStatusError as exc:
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)

    @mcp.tool()
    async def get_project_details(
        ctx: Context,
        project_id: Annotated[str, "Project ID (e.g., 'MyProject')."],
    ) -> dict[str, Any]:
        """Get detailed information about a single TeamCity project.

        Returns project metadata including: name, description, parent project,
        immediate child projects, build configurations defined in this project,
        and project parameters.

        Returns:
            Project details with nested child projects and build configurations.

        Example questions:
            - "Tell me about the Payments project"
            - "What build configs are in project X?"
            - "Show me the children of the Platform project"
        """
        try:
            project_id = v.external_id(project_id, "project_id")
        except v.InvalidArgument as exc:
            return v.invalid(exc)

        app = ctx.lifespan_context
        client = app.client

        try:
            params = {
                "fields": (
                    "id,name,description,archived,parentProjectId,webUrl,"
                    "parentProject(id,name),"
                    "buildTypes(buildType(id,name,description,paused,type)),"
                    "projects(project(id,name,description,archived)),"
                    "parameters(property(name,value))"
                ),
            }
            data = await client.get(f"/app/rest/projects/id:{project_id}", params=params)
            if not isinstance(data, dict):
                return {"error": f"Unexpected response for project '{project_id}'"}

            build_configs = []
            bt_data = data.get("buildTypes", {})
            for bt in bt_data.get("buildType", []) if isinstance(bt_data, dict) else []:
                build_configs.append(
                    {
                        "id": bt.get("id"),
                        "name": bt.get("name"),
                        "description": bt.get("description"),
                        "paused": bt.get("paused", False),
                        "type": bt.get("type"),
                    }
                )

            child_projects = []
            cp_data = data.get("projects", {})
            for cp in cp_data.get("project", []) if isinstance(cp_data, dict) else []:
                child_projects.append(
                    {
                        "id": cp.get("id"),
                        "name": cp.get("name"),
                        "description": cp.get("description"),
                        "archived": cp.get("archived", False),
                    }
                )

            parameters = {}
            param_data = data.get("parameters", {})
            for prop in param_data.get("property", []) if isinstance(param_data, dict) else []:
                parameters[prop.get("name")] = prop.get("value")

            parent = data.get("parentProject", {})
            logger.info(
                "get_project_details project_id=%s build_configs=%d child_projects=%d",
                project_id,
                len(build_configs),
                len(child_projects),
            )
            return {
                "id": data.get("id"),
                "name": data.get("name"),
                "description": data.get("description"),
                "archived": data.get("archived", False),
                "web_url": data.get("webUrl"),
                "parent_project": {"id": parent.get("id"), "name": parent.get("name")}
                if isinstance(parent, dict) and parent.get("id")
                else None,
                "build_configurations": build_configs,
                "build_config_count": len(build_configs),
                "child_projects": child_projects,
                "child_project_count": len(child_projects),
                "parameters": parameters,
            }

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return not_found("Project", project_id)
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)
