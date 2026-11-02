"""Fuzzy build-configuration search backed by the in-memory index."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from pydantic import Field

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def find_build_config(
        ctx: Context,
        query: Annotated[
            str,
            "Free-text query — partial names, project-path fragments, or abbreviations.",
        ],
        limit: Annotated[int, Field(description="Maximum results to return", ge=1, le=25)] = 10,
    ) -> dict[str, Any]:
        """Find build configurations by fuzzy name/project matching.

        The PRIMARY tool when a configuration is described in natural language,
        vague terms, abbreviations, or partial names — it matches against every
        configuration's name and full project path.

        Returns:
            Ranked matches with a relevance score (higher is better) and a
            name_score used to break ties. ``ambiguous`` is set when the top
            matches are too close to pick one; ``matching_projects`` lists
            projects whose path matches the query.

        Example questions:
            - "Find the build config for deploying the API"
            - "Which job handles nightly smoke tests?"
        """
        if not query or not query.strip():
            return {
                "error": "Query parameter is required",
                "reason": "Provide a text description to search for",
            }

        app = ctx.lifespan_context
        index = app.build_config_index

        if not index.loaded:
            if index.last_error:
                return {
                    "error": "Build-configuration index failed to load",
                    "reason": index.last_error,
                    "hint": "The server retries in the background; search_build_configs still works by ID.",
                }
            return {
                "error": "Build configurations not yet loaded",
                "reason": "Search is still initializing. Try again in a few seconds.",
            }

        query_clean = query.strip()
        results = index.search(query_clean, limit=limit)
        response: dict[str, Any] = {
            "results": results,
            "count": len(results),
            "total_configs": index.size,
            "query": query_clean,
        }
        if index.is_ambiguous(results):
            response["ambiguous"] = True
            response["note"] = "Top matches score about the same; confirm which one the user means."
        projects = index.search_projects(query_clean)
        if projects:
            response["matching_projects"] = projects
        if index.last_error:
            # Loaded earlier, but the latest refresh failed: results may be stale.
            response["warning"] = f"Index refresh failed, results may be stale: {index.last_error}"
        logger.debug("find_build_config query=%s results=%d", query_clean, len(results))
        return response
