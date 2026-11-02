"""URL resolution — convert TeamCity web URLs into structured identifiers."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastmcp import Context, FastMCP

from mcp_teamcity.url_parser import parse_teamcity_url

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def resolve_teamcity_url(
        ctx: Context,
        url: Annotated[
            str,
            "A TeamCity web UI URL from the browser address bar. Supports both "
            "new-style URLs (/project/X, /buildConfiguration/X/123, /build/123, /change/45) and legacy "
            "URLs (/viewLog.html?buildId=X, /viewType.html?buildTypeId=X, /project.html?projectId=X).",
        ],
    ) -> dict[str, Any]:
        """Parse a TeamCity web URL and extract entity identifiers.

        Users often paste URLs from their browser. This parses a TeamCity URL and
        extracts the project, build-configuration, and/or build IDs.

        Returns:
            Parsed URL with url_type ('project', 'build_config', 'build',
            'build_log', 'change', or 'unknown') and extracted IDs. Returns an error if the
            URL cannot be parsed.

        Example questions:
            - "What is this? https://tc.example.com/buildConfiguration/MyProject_Build/67890"
            - "Show me details for https://tc.example.com/project/MyProject"
            - "Why did this build fail? https://tc.example.com/viewLog.html?buildId=12345"
        """
        if not url or not url.strip():
            return {"error": "URL is required"}

        parsed = parse_teamcity_url(url.strip())

        if parsed.url_type == "unknown":
            logger.info("resolve_teamcity_url url_type=unknown")
            return {
                "error": "Could not parse TeamCity URL",
                "reason": (
                    "URL does not match known TeamCity patterns. Expected formats: "
                    "/project/{id}, /buildConfiguration/{id}, /buildConfiguration/{id}/{buildId}, "
                    "/build/{buildId}, /change/{changeId}, /viewLog.html?buildId={id}, "
                    "/viewType.html?buildTypeId={id}, /project.html?projectId={id}"
                ),
                "url": url,
            }

        result: dict[str, Any] = {"url_type": parsed.url_type, "url": url}
        if parsed.project_id:
            result["project_id"] = parsed.project_id
        if parsed.build_type_id:
            result["build_type_id"] = parsed.build_type_id
        if parsed.build_id:
            result["build_id"] = parsed.build_id
        if parsed.change_id:
            result["change_id"] = parsed.change_id
        if parsed.tab:
            result["tab"] = parsed.tab

        logger.info("resolve_teamcity_url url_type=%s", parsed.url_type)
        return result
