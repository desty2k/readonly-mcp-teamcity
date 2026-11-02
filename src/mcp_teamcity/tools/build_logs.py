"""Build log tools — retrieve and search build log content with pagination."""

from __future__ import annotations

import logging
from typing import Annotated, Any

import httpx
from fastmcp import Context, FastMCP

from mcp_teamcity import validation as v
from mcp_teamcity.errors import api_error, connection_error, not_found

logger = logging.getLogger(__name__)

# Maximum lines we'll ever return in a single call.
_MAX_LINES = 5000


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def get_build_log(
        ctx: Context,
        build_id: Annotated[str, "Numeric build ID"],
        start_line: Annotated[
            int | None,
            "Start reading from this line (0-indexed). Omit to start at the beginning.",
        ] = None,
        end_line: Annotated[
            int | None,
            "Stop reading at this line (exclusive). At most max_lines lines are returned even if the range is wider.",
        ] = None,
        max_lines: Annotated[int, "Maximum number of lines to return (capped at 5000)."] = 500,
        tail: Annotated[
            bool,
            "Return the last lines instead of the first — use when investigating failures.",
        ] = False,
    ) -> dict[str, Any]:
        """Retrieve build log content, paginated by line.

        Returns:
            Log text with start_line, end_line, total_lines, lines_returned, and
            a has_more flag.

        Example questions:
            - "Show me the build log for build 12345"
            - "What's at the end of the log for the failed build?"
            - "Show me lines 1000-1200 of the build log"
        """
        try:
            build_id = v.build_id(build_id)
        except v.InvalidArgument as exc:
            return v.invalid(exc)

        app = ctx.lifespan_context
        max_lines = max(1, min(max_lines, _MAX_LINES))

        try:
            build_log = await app.log_cache.get(app.client, build_id)
            all_lines = build_log.lines
            total_lines = len(all_lines)

            if total_lines == 0:
                return {
                    "build_id": build_id,
                    "log": "",
                    "start_line": 0,
                    "end_line": 0,
                    "total_lines": 0,
                    "lines_returned": 0,
                    "has_more": False,
                    "build_finished": build_log.finished,
                }

            if tail:
                actual_start = max(0, total_lines - max_lines)
                actual_end = total_lines
            elif start_line is not None and end_line is not None:
                # max_lines still applies: a wide range must not bypass the cap.
                actual_start = max(0, start_line)
                actual_end = min(total_lines, end_line, actual_start + max_lines)
            elif start_line is not None:
                actual_start = max(0, start_line)
                actual_end = min(total_lines, actual_start + max_lines)
            else:
                actual_start = 0
                actual_end = min(total_lines, max_lines)

            selected_lines = all_lines[actual_start:actual_end]
            logger.info(
                "get_build_log build_id=%s total_lines=%d returned=%d tail=%s",
                build_id,
                total_lines,
                len(selected_lines),
                tail,
            )
            return {
                "build_id": build_id,
                "log": "\n".join(selected_lines),
                "start_line": actual_start,
                "end_line": actual_end,
                "total_lines": total_lines,
                "lines_returned": len(selected_lines),
                "has_more": actual_end < total_lines,
                # A running build's log keeps growing; it is never cached.
                "build_finished": build_log.finished,
            }

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return not_found("Build log for build", build_id)
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)

    @mcp.tool()
    async def search_build_log(
        ctx: Context,
        build_id: Annotated[str, "Numeric build ID"],
        query: Annotated[str, "Text to find in the build log (case-insensitive)."],
        context_lines: Annotated[int, "Lines of context to show around each match."] = 3,
        max_matches: Annotated[int, "Maximum number of matches to return."] = 20,
    ) -> dict[str, Any]:
        """Search within a build log for specific text.

        Returns matching lines with surrounding context — find errors or patterns
        in large logs without paging through them.

        Returns:
            List of matches with line numbers and surrounding context, plus the
            total match count.

        Example questions:
            - "Find 'OutOfMemoryError' in the build log"
            - "Search for 'FAILED' in the log"
            - "Are there any deprecation warnings in this build?"
        """
        try:
            build_id = v.build_id(build_id)
        except v.InvalidArgument as exc:
            return v.invalid(exc)

        app = ctx.lifespan_context
        max_matches = max(1, min(max_matches, 100))
        context_lines = max(0, min(context_lines, 20))

        try:
            build_log = await app.log_cache.get(app.client, build_id)
            all_lines = build_log.lines
            total_lines = len(all_lines)
            query_lower = query.lower()

            match_indices = [i for i, line in enumerate(all_lines) if query_lower in line.lower()]
            total_matches = len(match_indices)

            matches: list[dict[str, Any]] = []
            for idx in match_indices[:max_matches]:
                ctx_start = max(0, idx - context_lines)
                ctx_end = min(total_lines, idx + context_lines + 1)
                context = [
                    {"line_number": j, "text": all_lines[j], "is_match": j == idx} for j in range(ctx_start, ctx_end)
                ]
                matches.append({"line_number": idx, "text": all_lines[idx], "context": context})

            logger.debug(
                "search_build_log build_id=%s query=%s total_matches=%d returned=%d",
                build_id,
                query,
                total_matches,
                len(matches),
            )
            return {
                "build_id": build_id,
                "query": query,
                "matches": matches,
                "matches_returned": len(matches),
                "total_matches": total_matches,
                "total_lines": total_lines,
                "truncated": total_matches > max_matches,
                "build_finished": build_log.finished,
            }

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return not_found("Build log for build", build_id)
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)
