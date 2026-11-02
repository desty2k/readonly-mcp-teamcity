"""Test-result tools — inspect test occurrences and individual failures."""

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
    async def get_build_test_results(
        ctx: Context,
        build_id: Annotated[str, "Numeric build ID"],
        status: Annotated[
            str | None,
            "Filter by test status: 'SUCCESS', 'FAILURE', or 'UNKNOWN'. "
            "Omit for all tests. Use 'FAILURE' to see only failed tests.",
        ] = None,
        page: Annotated[int, Field(description="Page number, 1-indexed", ge=1)] = 1,
        limit: Annotated[int, Field(description="Max results per page", ge=1, le=500)] = 50,
    ) -> dict[str, Any]:
        """Get test results for a build.

        Returns test occurrences with name, status, duration, and failure
        details. A build can have thousands of tests — use pagination and the
        status filter to focus on what matters.

        Returns:
            List of test occurrences with id, name, status, duration_ms, details,
            and investigation/muting flags.

        Example questions:
            - "What tests failed in this build?"
            - "How many tests passed in build 12345?"
            - "Which tests are flaky (UNKNOWN status)?"
        """
        try:
            build_id = v.build_id(build_id)
            status = v.status(status) if status else None
        except v.InvalidArgument as exc:
            return v.invalid(exc)

        app = ctx.lifespan_context
        client = app.client
        limit = clamp_limit(limit, app.settings.default_limit, app.settings.max_limit)
        page = max(1, page)
        offset = (page - 1) * limit

        try:
            locator_parts = [f"build:(id:{build_id})"]
            if status:
                locator_parts.append(f"status:{status.upper()}")
            locator_parts.append(f"count:{limit}")
            locator_parts.append(f"start:{offset}")

            params: dict[str, Any] = {
                "locator": ",".join(locator_parts),
                "fields": (
                    "count,nextHref,prevHref,testOccurrence(id,name,status,duration,details,"
                    "currentlyInvestigated,currentlyMuted,muted,newFailure,ignored,href,test(id,name))"
                ),
            }

            data = await client.get("/app/rest/testOccurrences", params=params)
            tests_list = data.get("testOccurrence", []) if isinstance(data, dict) else []

            results = []
            for t in tests_list:
                test_ref = t.get("test", {}) or {}
                results.append(
                    {
                        "id": t.get("id"),
                        "name": t.get("name"),
                        "status": t.get("status"),
                        "duration_ms": t.get("duration"),
                        "details": t.get("details"),
                        "currently_investigated": t.get("currentlyInvestigated", False),
                        "currently_muted": t.get("currentlyMuted", False),
                        "muted": t.get("muted", False),
                        "new_failure": t.get("newFailure", False),
                        "ignored": t.get("ignored", False),
                        "test_id": test_ref.get("id"),
                    }
                )

            logger.info("get_build_test_results build_id=%s status=%s count=%d", build_id, status, len(results))
            return {
                "build_id": build_id,
                "tests": results,
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
    async def get_test_details(
        ctx: Context,
        test_locator: Annotated[str, "Test occurrence locator (the 'id' field of a test occurrence)."],
    ) -> dict[str, Any]:
        """Get detailed information about a specific test occurrence.

        Returns the full test name, status, duration, failure reason, and
        investigation/muting state, plus the first-failed / next-fixed build
        references that bracket the failure.

        Example questions:
            - "Show me the details of this failed test"
            - "What was the error message for this test?"
            - "Is this test being investigated?"
        """
        try:
            test_locator = v.test_occurrence_id(test_locator)
        except v.InvalidArgument as exc:
            return v.invalid(exc)

        app = ctx.lifespan_context
        client = app.client

        try:
            params = {
                "fields": (
                    "id,name,status,duration,details,currentlyInvestigated,"
                    "currentlyMuted,firstFailed,nextFixed,href,test(id,name)"
                ),
            }
            data = await client.get(f"/app/rest/testOccurrences/{test_locator}", params=params)
            if not isinstance(data, dict):
                return {"error": f"Unexpected response for test '{test_locator}'"}

            test_ref = data.get("test", {}) or {}
            logger.info("get_test_details test_locator=%s status=%s", test_locator, data.get("status"))
            return {
                "id": data.get("id"),
                "name": data.get("name"),
                "status": data.get("status"),
                "duration_ms": data.get("duration"),
                "details": data.get("details"),
                "currently_investigated": data.get("currentlyInvestigated", False),
                "currently_muted": data.get("currentlyMuted", False),
                "first_failed": data.get("firstFailed"),
                "next_fixed": data.get("nextFixed"),
                "test_id": test_ref.get("id"),
                "test_name": test_ref.get("name"),
            }

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return not_found("Test occurrence", test_locator)
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)
