"""Build configuration tools — search configs and inspect their steps,
triggers, parameters, and branches."""

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


def _extract_properties(container: dict[str, Any] | None) -> dict[str, Any]:
    """Flatten a TeamCity ``properties(property(name,value))`` block to a dict."""
    props: dict[str, Any] = {}
    if not isinstance(container, dict):
        return props
    for p in container.get("property", []):
        props[p.get("name")] = p.get("value")
    return props


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def search_build_configs(
        ctx: Context,
        project_id: Annotated[
            str | None,
            "Filter by project ID. Returns only build configurations belonging to this project.",
        ] = None,
        build_type_id: Annotated[
            str | None,
            "Filter by exact build type ID (e.g., 'MyProject_Build'). Use when you know the exact identifier.",
        ] = None,
        paused: Annotated[bool | None, "Filter by paused state. None = all."] = None,
        page: Annotated[int, Field(description="Page number, 1-indexed", ge=1)] = 1,
        limit: Annotated[int, Field(description="Max results per page", ge=1, le=500)] = 50,
    ) -> dict[str, Any]:
        """Search TeamCity build configurations (jobs/pipelines) by structured filters.

        A build configuration defines WHAT to build and HOW — steps, triggers,
        parameters, and VCS roots. Each run produces a build. At least one filter
        (project_id or build_type_id) is required.

        Returns:
            List of build configurations with id, name, project_id, description,
            paused status, and type (regular/deployment/composite).

        Example questions:
            - "What build configs are in the Payments project?"
            - "Is the nightly build paused?"
        """
        if not any([project_id, build_type_id]):
            return {
                "error": "At least one filter required: project_id or build_type_id",
                "reason": "Prevents unbounded queries against TeamCity",
            }

        try:
            project_id = v.external_id(project_id, "project_id") if project_id else None
            build_type_id = v.external_id(build_type_id, "build_type_id") if build_type_id else None
        except v.InvalidArgument as exc:
            return v.invalid(exc)

        app = ctx.lifespan_context
        client = app.client
        limit = clamp_limit(limit, app.settings.default_limit, app.settings.max_limit)
        page = max(1, page)

        try:
            locator_parts: list[str] = []
            if build_type_id:
                locator_parts.append(f"id:{build_type_id}")
            if project_id:
                locator_parts.append(f"project:(id:{project_id})")
            if paused is not None:
                locator_parts.append(f"paused:{str(paused).lower()}")

            offset = (page - 1) * limit
            locator_parts.append(f"count:{limit}")
            locator_parts.append(f"start:{offset}")

            params: dict[str, Any] = {
                "locator": ",".join(locator_parts),
                "fields": (
                    "count,nextHref,prevHref,buildType(id,name,description,projectId,projectName,paused,type,webUrl)"
                ),
            }

            data = await client.get("/app/rest/buildTypes", params=params)
            configs = data.get("buildType", []) if isinstance(data, dict) else []

            results = []
            for bt in configs:
                results.append(
                    {
                        "id": bt.get("id"),
                        "name": bt.get("name"),
                        "description": bt.get("description"),
                        "project_id": bt.get("projectId"),
                        "project_name": bt.get("projectName"),
                        "paused": bt.get("paused", False),
                        "type": bt.get("type"),
                        "web_url": bt.get("webUrl"),
                    }
                )

            logger.info("search_build_configs project_id=%s count=%d", project_id, len(results))
            return {
                "build_configurations": results,
                "count": len(results),
                "pagination": build_pagination(page, limit, data),
            }

        except httpx.HTTPStatusError as exc:
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)

    @mcp.tool()
    async def get_build_config_details(
        ctx: Context,
        build_type_id: Annotated[str, "Build configuration ID (e.g., 'MyProject_Build')."],
    ) -> dict[str, Any]:
        """Get full details of a build configuration including steps, triggers, and parameters.

        Returns comprehensive configuration data: build steps (type, name, and
        properties), triggers (VCS, schedule, dependency), parameters, VCS roots,
        settings, and agent requirements.

        Use this to understand HOW a build is configured, not its run history.

        Returns:
            Full build configuration with steps, triggers, parameters, VCS roots,
            settings, and agent requirements.

        Example questions:
            - "What steps does the deploy pipeline have?"
            - "What triggers the nightly build?"
            - "What VCS roots does this build use?"
            - "What agent requirements does this build need?"
        """
        try:
            build_type_id = v.external_id(build_type_id, "build_type_id")
        except v.InvalidArgument as exc:
            return v.invalid(exc)

        app = ctx.lifespan_context
        client = app.client

        try:
            params = {
                "fields": (
                    "id,name,description,projectId,projectName,paused,type,webUrl,"
                    "steps(step(id,name,type,properties(property(name,value)))),"
                    "triggers(trigger(id,type,properties(property(name,value)))),"
                    "parameters(property(name,value,type(rawValue))),"
                    "vcs-root-entries(vcs-root-entry(id,vcs-root(id,name,vcsName))),"
                    "settings(property(name,value)),"
                    "agent-requirements(agent-requirement(id,type,properties(property(name,value))))"
                ),
            }
            data = await client.get(f"/app/rest/buildTypes/id:{build_type_id}", params=params)
            if not isinstance(data, dict):
                return {"error": f"Unexpected response for build config '{build_type_id}'"}

            steps = []
            steps_data = data.get("steps", {})
            for step in steps_data.get("step", []) if isinstance(steps_data, dict) else []:
                steps.append(
                    {
                        "id": step.get("id"),
                        "name": step.get("name"),
                        "type": step.get("type"),
                        "properties": _extract_properties(step.get("properties")),
                    }
                )

            triggers = []
            triggers_data = data.get("triggers", {})
            for trigger in triggers_data.get("trigger", []) if isinstance(triggers_data, dict) else []:
                triggers.append(
                    {
                        "id": trigger.get("id"),
                        "type": trigger.get("type"),
                        "properties": _extract_properties(trigger.get("properties")),
                    }
                )

            parameters = _extract_properties(data.get("parameters"))

            vcs_roots = []
            vcs_data = data.get("vcs-root-entries", {})
            for entry in vcs_data.get("vcs-root-entry", []) if isinstance(vcs_data, dict) else []:
                vcs_root = entry.get("vcs-root", {}) or {}
                vcs_roots.append(
                    {
                        "id": vcs_root.get("id"),
                        "name": vcs_root.get("name"),
                        "vcs_name": vcs_root.get("vcsName"),
                    }
                )

            settings_dict = _extract_properties(data.get("settings"))

            requirements = []
            req_data = data.get("agent-requirements", {})
            for req in req_data.get("agent-requirement", []) if isinstance(req_data, dict) else []:
                requirements.append(
                    {
                        "id": req.get("id"),
                        "type": req.get("type"),
                        "properties": _extract_properties(req.get("properties")),
                    }
                )

            logger.info(
                "get_build_config_details build_type_id=%s steps=%d triggers=%d",
                build_type_id,
                len(steps),
                len(triggers),
            )
            return {
                "id": data.get("id"),
                "name": data.get("name"),
                "description": data.get("description"),
                "project_id": data.get("projectId"),
                "project_name": data.get("projectName"),
                "paused": data.get("paused", False),
                "type": data.get("type"),
                "web_url": data.get("webUrl"),
                "steps": steps,
                "step_count": len(steps),
                "triggers": triggers,
                "trigger_count": len(triggers),
                "parameters": parameters,
                "vcs_roots": vcs_roots,
                "settings": settings_dict,
                "agent_requirements": requirements,
            }

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return not_found("Build configuration", build_type_id)
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)

    @mcp.tool()
    async def get_build_config_branches(
        ctx: Context,
        build_type_id: Annotated[str, "Build configuration ID"],
        page: Annotated[int, Field(description="Page number, 1-indexed", ge=1)] = 1,
        limit: Annotated[int, Field(description="Max results per page", ge=1, le=500)] = 50,
    ) -> dict[str, Any]:
        """List branches available for a build configuration.

        Returns branch names with their default status and activity information.
        Use this to understand which branches a configuration can build.

        Example questions:
            - "What branches can this build run on?"
            - "What is the default branch for this pipeline?"
        """
        try:
            build_type_id = v.external_id(build_type_id, "build_type_id")
        except v.InvalidArgument as exc:
            return v.invalid(exc)

        app = ctx.lifespan_context
        client = app.client
        limit = clamp_limit(limit, app.settings.default_limit, app.settings.max_limit)
        page = max(1, page)

        try:
            offset = (page - 1) * limit
            params: dict[str, Any] = {
                "locator": f"count:{limit},start:{offset}",
                "fields": "count,nextHref,prevHref,branch(name,default,active,lastActivity)",
            }
            data = await client.get(f"/app/rest/buildTypes/id:{build_type_id}/branches", params=params)
            branches_list = data.get("branch", []) if isinstance(data, dict) else []

            results = []
            for b in branches_list:
                results.append(
                    {
                        "name": b.get("name"),
                        "default": b.get("default", False),
                        "active": b.get("active", False),
                        "last_activity": b.get("lastActivity"),
                    }
                )

            logger.info("get_build_config_branches build_type_id=%s count=%d", build_type_id, len(results))
            return {
                "build_type_id": build_type_id,
                "branches": results,
                "count": len(results),
                "pagination": build_pagination(page, limit, data),
            }

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return not_found("Build configuration", build_type_id)
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)
