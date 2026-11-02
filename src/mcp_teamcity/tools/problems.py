"""Build-problem and investigation tools — why builds failed, and who's on it."""

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
    async def get_build_problems(
        ctx: Context,
        build_id: Annotated[str, "Numeric build ID"],
        page: Annotated[int, Field(description="Page number, 1-indexed", ge=1)] = 1,
        limit: Annotated[int, Field(description="Max results per page", ge=1, le=500)] = 50,
    ) -> dict[str, Any]:
        """Get problems detected in a build.

        Returns structured problem data: compilation errors, exit-code failures,
        test failures, snapshot-dependency failures, and custom problem types.
        Each problem has a type, identity, and description.

        This is the PRIMARY tool for understanding WHY a build failed — it is
        easier to interpret than raw logs.

        Returns:
            List of problem occurrences with type, identity, details, and the
            associated problem definition.

        Example questions:
            - "Why did this build fail?"
            - "Were there compilation errors?"
            - "Did a snapshot dependency fail?"
        """
        try:
            build_id = v.build_id(build_id)
        except v.InvalidArgument as exc:
            return v.invalid(exc)

        app = ctx.lifespan_context
        client = app.client
        limit = clamp_limit(limit, app.settings.default_limit, app.settings.max_limit)
        page = max(1, page)
        offset = (page - 1) * limit

        try:
            locator = f"build:(id:{build_id}),count:{limit},start:{offset}"
            params: dict[str, Any] = {
                "locator": locator,
                "fields": (
                    "count,nextHref,prevHref,problemOccurrence(id,type,identity,details,additionalData,"
                    "problem(id,type,identity,description),build(id,number,status))"
                ),
            }

            data = await client.get("/app/rest/problemOccurrences", params=params)
            problems_list = data.get("problemOccurrence", []) if isinstance(data, dict) else []

            results = []
            for po in problems_list:
                problem = po.get("problem", {}) or {}
                results.append(
                    {
                        "id": po.get("id"),
                        "type": po.get("type"),
                        "identity": po.get("identity"),
                        "details": po.get("details"),
                        "additional_data": po.get("additionalData"),
                        "problem_id": problem.get("id"),
                        "problem_type": problem.get("type"),
                        "problem_description": problem.get("description"),
                    }
                )

            logger.info("get_build_problems build_id=%s count=%d", build_id, len(results))
            return {
                "build_id": build_id,
                "problems": results,
                "count": len(results),
                "pagination": build_pagination(page, limit, data),
            }

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return not_found("Build", build_id)
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)

    @mcp.tool()
    async def search_investigations(
        ctx: Context,
        project_id: Annotated[str | None, "Filter investigations by project ID."] = None,
        build_type_id: Annotated[str | None, "Filter investigations by build configuration ID."] = None,
        assignee: Annotated[str | None, "Filter by assignee username."] = None,
        page: Annotated[int, Field(description="Page number, 1-indexed", ge=1)] = 1,
        limit: Annotated[int, Field(description="Max results per page", ge=1, le=500)] = 50,
    ) -> dict[str, Any]:
        """Search active investigations in TeamCity.

        Investigations are assignments to fix a failing build or test. When a
        build fails, TeamCity can assign an investigation to a team member.

        Returns:
            List of investigations with assignee, state, scope (build config or
            project), assignment metadata, and resolution details.

        Example questions:
            - "Who is investigating the build failure?"
            - "What investigations are assigned to user X?"
            - "Are there any open investigations in the Payments project?"
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
            if build_type_id:
                locator_parts.append(f"buildType:(id:{build_type_id})")
            if project_id:
                locator_parts.append(f"project:(id:{project_id})")
            if assignee:
                locator_parts.append(f"assignee:(username:{v.locator_value(assignee)})")
            locator_parts.append(f"count:{limit}")
            locator_parts.append(f"start:{offset}")

            params: dict[str, Any] = {
                "locator": ",".join(locator_parts),
                "fields": (
                    "count,nextHref,prevHref,investigation(id,state,"
                    "assignee(username,name),"
                    "assignment(timestamp,user(username,name),text),"
                    "scope(buildTypes(buildType(id,name,projectId)),project(id,name)),"
                    "target(anyProblem,tests(test(name)),problems(problem(id,description))),"
                    "resolution(type,time))"
                ),
            }

            data = await client.get("/app/rest/investigations", params=params)
            investigations = data.get("investigation", []) if isinstance(data, dict) else []

            results = []
            for inv in investigations:
                assignee_data = inv.get("assignee", {}) or {}
                assignment = inv.get("assignment", {}) or {}
                assignment_user = assignment.get("user", {}) or {}
                resolution = inv.get("resolution", {}) or {}

                scope_data = inv.get("scope", {}) or {}
                scope_build_types = []
                bt_container = scope_data.get("buildTypes", {})
                if isinstance(bt_container, dict):
                    for bt in bt_container.get("buildType", []):
                        scope_build_types.append(
                            {"id": bt.get("id"), "name": bt.get("name"), "project_id": bt.get("projectId")}
                        )
                scope_project = scope_data.get("project", {}) or {}

                results.append(
                    {
                        "id": inv.get("id"),
                        "state": inv.get("state"),
                        "assignee": assignee_data.get("username"),
                        "assignee_name": assignee_data.get("name"),
                        "assigned_by": assignment_user.get("username"),
                        "assignment_text": assignment.get("text"),
                        "assignment_timestamp": assignment.get("timestamp"),
                        "scope_build_types": scope_build_types,
                        "scope_project": {"id": scope_project.get("id"), "name": scope_project.get("name")}
                        if scope_project.get("id")
                        else None,
                        "resolution_type": resolution.get("type"),
                        "resolution_time": resolution.get("time"),
                    }
                )

            logger.info(
                "search_investigations project_id=%s build_type_id=%s count=%d",
                project_id,
                build_type_id,
                len(results),
            )
            return {
                "investigations": results,
                "count": len(results),
                "pagination": build_pagination(page, limit, data),
            }

        except httpx.HTTPStatusError as exc:
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)

    @mcp.tool()
    async def list_muted_tests(
        ctx: Context,
        project_id: Annotated[str | None, "Filter mutes by project ID."] = None,
        build_type_id: Annotated[str | None, "Filter mutes by build configuration ID."] = None,
        page: Annotated[int, Field(description="Page number, 1-indexed", ge=1)] = 1,
        limit: Annotated[int, Field(description="Max results per page", ge=1, le=500)] = 50,
    ) -> dict[str, Any]:
        """List currently muted tests.

        A muted test does not fail its build even when it fails, so a mute can
        hide a real regression. This returns who muted what, where (scope), why,
        and how it resolves.

        Returns:
            List of mutes with the muted tests, scope (project/build configs),
            who muted them and when, and the resolution policy.

        Example questions:
            - "What tests are muted in the Payments project?"
            - "Is this failing test muted, and who muted it?"
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
            if build_type_id:
                locator_parts.append(f"buildType:(id:{build_type_id})")
            if project_id:
                locator_parts.append(f"project:(id:{project_id})")
            locator_parts.append(f"count:{limit}")
            locator_parts.append(f"start:{offset}")

            params: dict[str, Any] = {
                "locator": ",".join(locator_parts),
                "fields": (
                    "count,nextHref,prevHref,mute(id,"
                    "assignment(text,timestamp,user(username,name)),"
                    "scope(project(id,name),buildTypes(buildType(id,name))),"
                    "target(tests(test(id,name))),"
                    "resolution(type,time))"
                ),
            }

            data = await client.get("/app/rest/mutes", params=params)
            mutes = data.get("mute", []) if isinstance(data, dict) else []

            results = []
            for m in mutes:
                assignment = m.get("assignment", {}) or {}
                assignment_user = assignment.get("user", {}) or {}
                resolution = m.get("resolution", {}) or {}
                scope_data = m.get("scope", {}) or {}
                scope_project = scope_data.get("project", {}) or {}

                bt_container = scope_data.get("buildTypes", {})
                scope_build_types = []
                if isinstance(bt_container, dict):
                    for bt in bt_container.get("buildType", []):
                        scope_build_types.append({"id": bt.get("id"), "name": bt.get("name")})

                target = m.get("target", {}) or {}
                tests_container = target.get("tests", {}) or {}
                test_names = []
                if isinstance(tests_container, dict):
                    for t in tests_container.get("test", []):
                        test_names.append(t.get("name"))

                results.append(
                    {
                        "id": m.get("id"),
                        "tests": test_names,
                        "muted_by": assignment_user.get("username"),
                        "mute_text": assignment.get("text"),
                        "muted_at": assignment.get("timestamp"),
                        "scope_project": {"id": scope_project.get("id"), "name": scope_project.get("name")}
                        if scope_project.get("id")
                        else None,
                        "scope_build_types": scope_build_types,
                        "resolution_type": resolution.get("type"),
                    }
                )

            logger.info(
                "list_muted_tests project_id=%s build_type_id=%s count=%d", project_id, build_type_id, len(results)
            )
            return {
                "mutes": results,
                "count": len(results),
                "pagination": build_pagination(page, limit, data),
            }

        except httpx.HTTPStatusError as exc:
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)
