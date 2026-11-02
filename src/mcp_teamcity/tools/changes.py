"""VCS-change tools — browse commits tracked by TeamCity."""

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
    async def search_changes(
        ctx: Context,
        build_id: Annotated[str | None, "Get VCS changes included in a specific build."] = None,
        build_type_id: Annotated[str | None, "Get pending changes for a build configuration."] = None,
        project_id: Annotated[str | None, "Get changes across all build configurations in a project."] = None,
        username: Annotated[str | None, "Filter changes by VCS username (committer)."] = None,
        since_change: Annotated[
            str | None,
            "Only changes after this one: a TeamCity change ID (e.g. '1234') or a full commit SHA.",
        ] = None,
        page: Annotated[int, Field(description="Page number, 1-indexed", ge=1)] = 1,
        limit: Annotated[int, Field(description="Max results per page", ge=1, le=500)] = 50,
    ) -> dict[str, Any]:
        """Search VCS changes (commits) tracked by TeamCity.

        Returns changes with author, date, comment, and file count. Changes are
        linked to the builds that include them. At least one filter is required:
        build_id, build_type_id, project_id, or username.

        Returns:
            List of changes with id, version (commit hash), username, date,
            comment, web_url, and file_count.

        Example questions:
            - "What commits are in build 12345?"
            - "What did user X commit recently?"
            - "What changes are pending for the deploy pipeline?"
        """
        if not any([build_id, build_type_id, project_id, username]):
            return {
                "error": "At least one filter required: build_id, build_type_id, project_id, or username",
                "reason": "Prevents unbounded queries against TeamCity",
            }

        try:
            build_id = v.build_id(build_id) if build_id else None
            build_type_id = v.external_id(build_type_id, "build_type_id") if build_type_id else None
            project_id = v.external_id(project_id, "project_id") if project_id else None
        except v.InvalidArgument as exc:
            return v.invalid(exc)

        app = ctx.lifespan_context
        client = app.client
        limit = clamp_limit(limit, app.settings.default_limit, app.settings.max_limit)
        page = max(1, page)
        offset = (page - 1) * limit

        try:
            locator_parts: list[str] = []
            if build_id:
                locator_parts.append(f"build:(id:{build_id})")
            if build_type_id:
                locator_parts.append(f"buildType:(id:{build_type_id})")
            if project_id:
                locator_parts.append(f"project:(id:{project_id})")
            if username:
                locator_parts.append(f"username:{v.locator_value(username)}")
            if since_change:
                since = since_change.strip()
                if since.isdigit():
                    locator_parts.append(f"sinceChange:{since}")
                else:
                    locator_parts.append(f"sinceChange:(version:{v.locator_value(since)})")
            locator_parts.append(f"count:{limit}")
            locator_parts.append(f"start:{offset}")

            params: dict[str, Any] = {
                "locator": ",".join(locator_parts),
                "fields": ("count,nextHref,prevHref,change(id,version,username,date,comment,webUrl,files(count))"),
            }

            data = await client.get("/app/rest/changes", params=params)
            changes_list = data.get("change", []) if isinstance(data, dict) else []

            results = []
            for c in changes_list:
                files_data = c.get("files", {}) or {}
                results.append(
                    {
                        "id": c.get("id"),
                        "version": c.get("version"),
                        "username": c.get("username"),
                        "date": c.get("date"),
                        "comment": c.get("comment"),
                        "web_url": c.get("webUrl"),
                        "file_count": (files_data.get("count", 0) if isinstance(files_data, dict) else 0),
                    }
                )

            logger.debug("search_changes build_id=%s username=%s count=%d", build_id, username, len(results))
            return {
                "changes": results,
                "count": len(results),
                "pagination": build_pagination(page, limit, data),
            }

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404 and since_change:
                return {
                    "error": f"No change found for since_change '{since_change}'",
                    "reason": "Use a TeamCity change ID or the full commit SHA; abbreviated SHAs do not match.",
                }
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)

    @mcp.tool()
    async def get_change_details(
        ctx: Context,
        change_id: Annotated[str, "Change ID"],
    ) -> dict[str, Any]:
        """Get detailed information about a VCS change including modified files.

        Returns the full commit details with the complete list of modified files
        (added, modified, deleted) and their paths.

        Example questions:
            - "What files were changed in this commit?"
            - "Show me the details of change 12345"
        """
        try:
            change_id = v.numeric_id(change_id, "change_id")
        except v.InvalidArgument as exc:
            return v.invalid(exc)

        app = ctx.lifespan_context
        client = app.client

        try:
            params = {
                "fields": (
                    "id,version,username,date,comment,webUrl,"
                    "vcsRootInstance(name,vcs-root(id,name)),"
                    "files(file(file,changeType,relativePath))"
                ),
            }
            data = await client.get(f"/app/rest/changes/id:{change_id}", params=params)
            if not isinstance(data, dict):
                return {"error": f"Unexpected response for change '{change_id}'"}

            files = []
            files_data = data.get("files", {})
            for f in files_data.get("file", []) if isinstance(files_data, dict) else []:
                files.append(
                    {
                        "path": f.get("file") or f.get("relativePath"),
                        "change_type": f.get("changeType"),
                    }
                )

            vcs_instance = data.get("vcsRootInstance", {}) or {}
            vcs_root = vcs_instance.get("vcs-root", {}) or {}

            logger.info("get_change_details change_id=%s files=%d", change_id, len(files))
            return {
                "id": data.get("id"),
                "version": data.get("version"),
                "username": data.get("username"),
                "date": data.get("date"),
                "comment": data.get("comment"),
                "web_url": data.get("webUrl"),
                "vcs_root_id": vcs_root.get("id"),
                "vcs_root_name": (vcs_root.get("name") or vcs_instance.get("name")),
                "files": files,
                "file_count": len(files),
            }

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return not_found("Change", change_id)
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)
