"""Build-artifact tools — browse the artifact tree and read text artifacts."""

from __future__ import annotations

import logging
from typing import Annotated, Any

import httpx
from fastmcp import Context, FastMCP

from mcp_teamcity import validation as v
from mcp_teamcity.errors import api_error, connection_error, not_found

logger = logging.getLogger(__name__)

# Artifacts larger than this are refused (download from the UI instead).
_MAX_ARTIFACT_BYTES = 5_000_000
_MAX_CONTENT_LINES = 2000
_MAX_LINE_CHARS_CEIL = 20_000
_DEFAULT_LINE_CHARS = 2000


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def list_build_artifacts(
        ctx: Context,
        build_id: Annotated[str, "Numeric build ID"],
        path: Annotated[str, "Artifact directory to list (e.g. 'reports'). Empty lists the root."] = "",
    ) -> dict[str, Any]:
        """List the artifacts a build produced (one directory level).

        Browse into a directory by passing its path back in.

        Returns:
            Artifact entries with name, path, size_bytes, is_directory, modified.

        Example questions:
            - "What artifacts did build 12345 produce?"
            - "List the files under the test-reports directory of this build."
        """
        try:
            build_id = v.build_id(build_id)
            path = v.artifact_path(path)
        except v.InvalidArgument as exc:
            return v.invalid(exc)

        app = ctx.lifespan_context
        client = app.client
        clean_path = path
        url = f"/app/rest/builds/id:{build_id}/artifacts/children/{v.quote_path(clean_path)}"

        try:
            data = await client.get(
                url,
                params={"fields": "file(name,fullName,size,modificationTime,children(href),content(href))"},
            )
            files = data.get("file", []) if isinstance(data, dict) else []

            results = []
            for f in files:
                is_dir = bool(f.get("children"))
                results.append(
                    {
                        "name": f.get("name"),
                        "path": f.get("fullName"),
                        "size_bytes": f.get("size"),
                        "is_directory": is_dir,
                        "modified": f.get("modificationTime"),
                    }
                )

            logger.info("list_build_artifacts build_id=%s path=%s count=%d", build_id, clean_path or "/", len(results))
            return {"build_id": build_id, "path": clean_path, "artifacts": results, "count": len(results)}

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return not_found("Artifacts for build", build_id)
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)

    @mcp.tool()
    async def get_build_artifact_content(
        ctx: Context,
        build_id: Annotated[str, "Numeric build ID"],
        path: Annotated[str, "Artifact path, e.g. 'reports/junit.xml'."],
        start_line: Annotated[int, "First line to return (0-indexed)."] = 0,
        max_lines: Annotated[int, "Maximum lines to return."] = 200,
        max_line_length: Annotated[
            int, "Maximum characters per line; longer lines are truncated."
        ] = _DEFAULT_LINE_CHARS,
    ) -> dict[str, Any]:
        """Read the text content of a build artifact, paginated by line.

        Intended for text artifacts (test reports, coverage summaries, logs).
        Page a large file by advancing start_line while has_more is true.
        Oversized artifacts are refused.

        Returns:
            The requested lines with total_lines, has_more, and truncated_lines.

        Example questions:
            - "Show me the junit.xml report from build 12345."
            - "Read the coverage summary artifact."
        """
        try:
            build_id = v.build_id(build_id)
            path = v.artifact_path(path)
        except v.InvalidArgument as exc:
            return v.invalid(exc)

        app = ctx.lifespan_context
        client = app.client
        max_lines = max(1, min(max_lines, _MAX_CONTENT_LINES))
        max_line_length = max(1, min(max_line_length, _MAX_LINE_CHARS_CEIL))
        start_line = max(0, start_line)
        clean_path = path
        encoded = v.quote_path(clean_path)

        try:
            # Check size first so we never pull a huge/binary blob into context.
            meta = await client.get(
                f"/app/rest/builds/id:{build_id}/artifacts/metadata/{encoded}",
                params={"fields": "name,size"},
            )
            size = meta.get("size") if isinstance(meta, dict) else None
            if isinstance(size, int) and size > _MAX_ARTIFACT_BYTES:
                return {
                    "error": f"Artifact too large to inline ({size} bytes)",
                    "reason": f"Limit is {_MAX_ARTIFACT_BYTES} bytes; download it from the TeamCity UI instead.",
                    "build_id": build_id,
                    "path": clean_path,
                    "size_bytes": size,
                }

            text = await client.get_text(f"/app/rest/builds/id:{build_id}/artifacts/content/{encoded}")
            all_lines = text.splitlines()
            total_lines = len(all_lines)
            end = min(total_lines, start_line + max_lines)

            truncated_lines = 0
            selected: list[str] = []
            for line in all_lines[start_line:end]:
                if len(line) > max_line_length:
                    dropped = len(line) - max_line_length
                    selected.append(f"{line[:max_line_length]}… [+{dropped} chars truncated]")
                    truncated_lines += 1
                else:
                    selected.append(line)

            logger.info(
                "get_build_artifact_content build_id=%s path=%s lines=%d truncated=%d",
                build_id,
                clean_path,
                len(selected),
                truncated_lines,
            )
            return {
                "build_id": build_id,
                "path": clean_path,
                "content": "\n".join(selected),
                "start_line": start_line,
                "end_line": end,
                "total_lines": total_lines,
                "has_more": end < total_lines,
                "truncated_lines": truncated_lines,
            }

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return not_found("Artifact", clean_path)
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)
