"""Build tools — search build history and inspect individual builds."""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

import httpx
from fastmcp import Context, FastMCP
from pydantic import Field

from mcp_teamcity import validation as v
from mcp_teamcity.errors import api_error, connection_error, not_found
from mcp_teamcity.pagination import build_pagination, clamp_limit

logger = logging.getLogger(__name__)


def _build_locator(
    *,
    build_type_id: str | None = None,
    project_id: str | None = None,
    status: str | None = None,
    branch: str | None = None,
    running: bool | None = None,
    tag: str | None = None,
    since_date: str | None = None,
    until_date: str | None = None,
    build_number: str | None = None,
    personal: bool | None = None,
    count: int = 50,
    start: int = 0,
) -> str:
    """Build a TeamCity build-locator string from parameters.

    Raises :class:`validation.InvalidArgument` for malformed IDs, statuses or
    dates; free-text values are escaped.
    """
    parts: list[str] = []

    if build_type_id:
        parts.append(f"buildType:(id:{v.external_id(build_type_id, 'build_type_id')})")
    if project_id:
        parts.append(f"project:(id:{v.external_id(project_id, 'project_id')})")
    if status:
        parts.append(f"status:{v.status(status)}")
    if branch:
        if branch == "<default>":
            parts.append("branch:(default:true)")
        else:
            parts.append(f"branch:(name:(value:{v.locator_value(branch)},matchType:equals))")
    else:
        # Without a branch dimension TeamCity returns default-branch builds only.
        parts.append("branch:(default:any)")
    if running is not None:
        parts.append(f"running:{str(running).lower()}")
    if tag:
        parts.append(f"tag:{v.locator_value(tag)}")
    # Date dimensions with before/after conditions.
    if since_date:
        parts.append(f"startDate:(date:{v.date(since_date, 'since_date')},condition:after)")
    if until_date:
        parts.append(f"finishDate:(date:{v.date(until_date, 'until_date')},condition:before)")
    if build_number:
        parts.append(f"number:{v.locator_value(build_number)}")
    if personal is not None:
        parts.append(f"personal:{str(personal).lower()}")

    parts.append(f"count:{count}")
    parts.append(f"start:{start}")

    return ",".join(parts)


def _extract_properties(container: dict[str, Any] | None) -> dict[str, Any]:
    props: dict[str, Any] = {}
    if not isinstance(container, dict):
        return props
    for p in container.get("property", []):
        props[p.get("name")] = p.get("value")
    return props


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def search_builds(
        ctx: Context,
        build_type_id: Annotated[
            str | None,
            "Filter by build configuration ID. Use this to get history for a specific pipeline.",
        ] = None,
        project_id: Annotated[
            str | None,
            "Filter by project ID. Returns builds from all configurations in the project.",
        ] = None,
        status: Annotated[
            str | None,
            "Filter by build status: 'SUCCESS', 'FAILURE', or 'ERROR'. Omit to return all statuses.",
        ] = None,
        branch: Annotated[
            str | None,
            "Filter by branch name. Use '<default>' for the default branch. Omit to return builds from all branches.",
        ] = None,
        running: Annotated[
            bool | None,
            "Filter by running state. True = only running builds, False = only finished, None = all builds.",
        ] = None,
        tag: Annotated[str | None, "Filter by build tag (exact match)"] = None,
        since_date: Annotated[
            str | None,
            "Only builds started after this date. ISO 8601 format: 'yyyyMMddTHHmmss+0000'. "
            "Example: '20240101T000000+0000' for Jan 1 2024 UTC.",
        ] = None,
        until_date: Annotated[
            str | None,
            "Only builds that finished before this date. Same format as since_date.",
        ] = None,
        build_number: Annotated[
            str | None,
            "Filter by exact build number (display string, e.g., '1.2.3-456'). "
            "Build numbers are NOT numeric IDs — they are display strings.",
        ] = None,
        personal: Annotated[
            bool | None,
            "Filter personal builds. True = only personal, False = exclude personal, None = all.",
        ] = None,
        page: Annotated[int, Field(description="Page number, 1-indexed", ge=1)] = 1,
        limit: Annotated[int, Field(description="Max results per page", ge=1, le=500)] = 50,
    ) -> dict[str, Any]:
        """Search build history with filters.

        This is the PRIMARY tool for finding builds (CI/CD runs). At least one
        filter is required: build_type_id, project_id, status, running, tag, or
        branch. Builds are returned newest-first.

        Returns:
            List of builds with id, number, status, state, branch_name, dates,
            web_url, build type reference, and triggered-by info.

        Example questions:
            - "Show me the last 10 builds for the API deploy pipeline"
            - "What builds failed today?"
            - "List running builds"
            - "Show me builds on the release/2.0 branch"
        """
        has_filter = any([build_type_id, project_id, status, running is not None, tag, branch])
        if not has_filter:
            return {
                "error": ("At least one filter required: build_type_id, project_id, status, running, tag, or branch"),
                "reason": "Prevents unbounded queries against TeamCity",
            }

        app = ctx.lifespan_context
        client = app.client
        limit = clamp_limit(limit, app.settings.default_limit, app.settings.max_limit)
        page = max(1, page)
        offset = (page - 1) * limit

        try:
            try:
                locator = _build_locator(
                    build_type_id=build_type_id,
                    project_id=project_id,
                    status=status,
                    branch=branch,
                    running=running,
                    tag=tag,
                    since_date=since_date,
                    until_date=until_date,
                    build_number=build_number,
                    personal=personal,
                    count=limit,
                    start=offset,
                )
            except v.InvalidArgument as exc:
                return v.invalid(exc)

            params: dict[str, Any] = {
                "locator": locator,
                "fields": (
                    "count,nextHref,prevHref,build(id,number,status,state,branchName,"
                    "defaultBranch,startDate,finishDate,queuedDate,webUrl,"
                    "buildType(id,name,projectId),"
                    "triggered(type,user(username,name)),"
                    "statusText,personal)"
                ),
            }

            data = await client.get("/app/rest/builds", params=params)
            builds_list = data.get("build", []) if isinstance(data, dict) else []

            results = []
            for b in builds_list:
                triggered = b.get("triggered", {}) or {}
                triggered_user = triggered.get("user", {}) or {}
                build_type = b.get("buildType", {}) or {}
                results.append(
                    {
                        "id": b.get("id"),
                        "number": b.get("number"),
                        "status": b.get("status"),
                        "state": b.get("state"),
                        "status_text": b.get("statusText"),
                        "branch_name": b.get("branchName"),
                        "default_branch": b.get("defaultBranch", False),
                        "personal": b.get("personal", False),
                        "start_date": b.get("startDate"),
                        "finish_date": b.get("finishDate"),
                        "queued_date": b.get("queuedDate"),
                        "web_url": b.get("webUrl"),
                        "build_type_id": build_type.get("id"),
                        "build_type_name": build_type.get("name"),
                        "project_id": build_type.get("projectId"),
                        "triggered_by": triggered.get("type"),
                        "triggered_by_user": triggered_user.get("username"),
                    }
                )

            logger.info(
                "search_builds build_type_id=%s project_id=%s status=%s count=%d",
                build_type_id,
                project_id,
                status,
                len(results),
            )
            return {
                "builds": results,
                "count": len(results),
                "pagination": build_pagination(page, limit, data),
            }

        except httpx.HTTPStatusError as exc:
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)

    @mcp.tool()
    async def get_build_details(
        ctx: Context,
        build_id: Annotated[str, "Numeric build ID — the internal ID, not the build number."],
    ) -> dict[str, Any]:
        """Get comprehensive details of a single build.

        Returns full build data: status, state, branch, triggered-by, build
        agent, VCS revisions, parameters, output parameters, statistics,
        snapshot dependencies, and tags.

        Returns:
            Complete build details with status, timing, agent, revisions,
            parameters, and statistics.

        Example questions:
            - "Tell me about build 12345"
            - "What agent ran this build?"
            - "What revision was built?"
            - "What triggered this build?"
        """
        try:
            build_id = v.build_id(build_id)
        except v.InvalidArgument as exc:
            return v.invalid(exc)

        app = ctx.lifespan_context
        client = app.client

        try:
            params = {
                "fields": (
                    "id,number,status,state,statusText,branchName,"
                    "defaultBranch,startDate,finishDate,queuedDate,personal,webUrl,"
                    "buildType(id,name,description,projectId,projectName),"
                    "triggered(type,date,user(username,name)),"
                    "agent(id,name,typeId),"
                    "revisions(revision(version,vcs-root-instance(name,vcs-root(id,name)))),"
                    "properties(property(name,value)),"
                    "resulting-properties(property(name,value)),"
                    "statistics(property(name,value)),"
                    "snapshot-dependencies(build(id,number,status,buildType(id,name))),"
                    "testOccurrences(count,passed,failed,ignored,muted,newFailed),"
                    "tags(tag(name))"
                ),
            }
            data = await client.get(f"/app/rest/builds/id:{build_id}", params=params)
            if not isinstance(data, dict):
                return {"error": f"Unexpected response for build '{build_id}'"}

            build_type = data.get("buildType", {}) or {}
            triggered = data.get("triggered", {}) or {}
            triggered_user = triggered.get("user", {}) or {}
            agent = data.get("agent", {}) or {}

            revisions = []
            rev_data = data.get("revisions", {})
            for rev in rev_data.get("revision", []) if isinstance(rev_data, dict) else []:
                vcs_instance = rev.get("vcs-root-instance", {}) or {}
                vcs_root = vcs_instance.get("vcs-root", {}) or {}
                revisions.append(
                    {
                        "version": rev.get("version"),
                        "vcs_root_id": vcs_root.get("id"),
                        "vcs_root_name": (vcs_root.get("name") or vcs_instance.get("name")),
                    }
                )

            parameters = _extract_properties(data.get("properties"))
            output_params = _extract_properties(data.get("resulting-properties"))
            statistics = _extract_properties(data.get("statistics"))

            dependencies = []
            dep_data = data.get("snapshot-dependencies", {})
            for dep in dep_data.get("build", []) if isinstance(dep_data, dict) else []:
                dep_bt = dep.get("buildType", {}) or {}
                dependencies.append(
                    {
                        "build_id": dep.get("id"),
                        "build_number": dep.get("number"),
                        "status": dep.get("status"),
                        "build_type_id": dep_bt.get("id"),
                        "build_type_name": dep_bt.get("name"),
                    }
                )

            tags = []
            tags_data = data.get("tags", {})
            for tag in tags_data.get("tag", []) if isinstance(tags_data, dict) else []:
                tags.append(tag.get("name"))

            to_data = data.get("testOccurrences", {}) or {}
            test_summary = (
                {
                    "total": to_data.get("count"),
                    "passed": to_data.get("passed"),
                    "failed": to_data.get("failed"),
                    "ignored": to_data.get("ignored"),
                    "muted": to_data.get("muted"),
                    "new_failed": to_data.get("newFailed"),
                }
                if isinstance(to_data, dict) and to_data
                else None
            )

            logger.info("get_build_details build_id=%s status=%s", build_id, data.get("status"))
            return {
                "id": data.get("id"),
                "number": data.get("number"),
                "status": data.get("status"),
                "state": data.get("state"),
                "status_text": data.get("statusText"),
                "branch_name": data.get("branchName"),
                "default_branch": data.get("defaultBranch", False),
                "personal": data.get("personal", False),
                "start_date": data.get("startDate"),
                "finish_date": data.get("finishDate"),
                "queued_date": data.get("queuedDate"),
                "web_url": data.get("webUrl"),
                "build_type": {
                    "id": build_type.get("id"),
                    "name": build_type.get("name"),
                    "description": build_type.get("description"),
                    "project_id": build_type.get("projectId"),
                    "project_name": build_type.get("projectName"),
                },
                "triggered": {
                    "type": triggered.get("type"),
                    "date": triggered.get("date"),
                    "user": triggered_user.get("username"),
                    "user_name": triggered_user.get("name"),
                },
                "agent": {"id": agent.get("id"), "name": agent.get("name"), "type_id": agent.get("typeId")}
                if agent.get("id")
                else None,
                "revisions": revisions,
                "parameters": parameters,
                "output_parameters": output_params,
                "statistics": statistics,
                "snapshot_dependencies": dependencies,
                "test_summary": test_summary,
                "tags": tags,
            }

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return not_found("Build", build_id)
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)

    @mcp.tool()
    async def get_build_statistics(
        ctx: Context,
        build_id: Annotated[str, "Numeric build ID"],
    ) -> dict[str, Any]:
        """Get statistical metrics for a build.

        Returns numeric statistics: total duration, build step durations,
        artifact size, test counts (passed/failed/ignored/muted), code coverage
        metrics, and any custom statistics reported by build steps.

        Example questions:
            - "How long did each step take in this build?"
            - "What's the test pass rate for this build?"
            - "What was the code coverage?"
        """
        try:
            build_id = v.build_id(build_id)
        except v.InvalidArgument as exc:
            return v.invalid(exc)

        app = ctx.lifespan_context
        client = app.client

        try:
            data = await client.get(
                f"/app/rest/builds/id:{build_id}/statistics",
                params={"fields": "property(name,value)"},
            )
            statistics = _extract_properties(data if isinstance(data, dict) else None)
            logger.info("get_build_statistics build_id=%s metrics=%d", build_id, len(statistics))
            return {"build_id": build_id, "statistics": statistics}

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return not_found("Build", build_id)
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)

    @mcp.tool()
    async def get_build_chain(
        ctx: Context,
        build_id: Annotated[str, "Numeric build ID"],
        direction: Annotated[
            Literal["upstream", "downstream", "both"],
            "Which snapshot-dependency direction to traverse. 'upstream' = builds this one "
            "depends on; 'downstream' = builds that depend on this one; 'both' (default).",
        ] = "both",
    ) -> dict[str, Any]:
        """Traverse a build's snapshot-dependency chain.

        Answers "what did this build depend on?" (upstream) and "what depended on
        this build?" (downstream) — the core of pipeline/build-chain debugging.

        Returns:
            For each requested direction, a list of builds with id, number,
            status, state, and build type reference.

        Example questions:
            - "What builds does build 12345 depend on?"
            - "What downstream builds were triggered by this build?"
            - "Show me the full dependency chain for this build."
        """
        try:
            build_id = v.build_id(build_id)
        except v.InvalidArgument as exc:
            return v.invalid(exc)

        app = ctx.lifespan_context
        client = app.client
        fields = "build(id,number,status,state,buildType(id,name,projectId))"

        async def _fetch(relation: str) -> list[dict[str, Any]]:
            params = {
                "locator": f"snapshotDependency:({relation}:(id:{build_id})),count:200",
                "fields": fields,
            }
            data = await client.get("/app/rest/builds", params=params)
            builds_list = data.get("build", []) if isinstance(data, dict) else []
            shaped = []
            for b in builds_list:
                bt = b.get("buildType", {}) or {}
                shaped.append(
                    {
                        "id": b.get("id"),
                        "number": b.get("number"),
                        "status": b.get("status"),
                        "state": b.get("state"),
                        "build_type_id": bt.get("id"),
                        "build_type_name": bt.get("name"),
                    }
                )
            return shaped

        try:
            result: dict[str, Any] = {"build_id": build_id}
            if direction in ("upstream", "both"):
                result["depends_on"] = await _fetch("to")
            if direction in ("downstream", "both"):
                result["dependents"] = await _fetch("from")

            logger.info(
                "get_build_chain build_id=%s direction=%s upstream=%d downstream=%d",
                build_id,
                direction,
                len(result.get("depends_on", [])),
                len(result.get("dependents", [])),
            )
            return result

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return not_found("Build", build_id)
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)
