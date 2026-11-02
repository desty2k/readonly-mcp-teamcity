"""One-call failure diagnosis: build summary, problems, failed tests, error log lines."""

from __future__ import annotations

import logging
import re
from typing import Annotated, Any

import httpx
from fastmcp import Context, FastMCP
from pydantic import Field

from mcp_teamcity import validation as v
from mcp_teamcity.errors import api_error, connection_error, not_found

logger = logging.getLogger(__name__)

# TeamCity's plain log marks error and warning messages with "]E:" / "]W:".
_MARKED_RE = re.compile(r"^\[[\d:.]+\][EW]:")
# Block-opening lines ("]E: bt4 (10s)", "]E: Step 1/1: run (Command Line)") are
# marked too when the block failed, but say nothing about why.
_BLOCK_HEADER_RE = re.compile(r"^\[[\d:.]+\][EW]: (bt\d+( \(|$)|Step \d+/\d+: )")
# Unmarked output that usually explains a failure.
_KEYWORD_RE = re.compile(
    r"\b(error|exception|fatal|traceback|panic|segmentation fault|killed|timed out|timeout)\b|OutOfMemory",
    re.IGNORECASE,
)
_TIMESTAMPED_RE = re.compile(r"^\[[\d:.]+\]")
# TeamCity's own summaries of failed tests; failed_tests already covers them.
_TEST_SUMMARY_RE = re.compile(r"(Failed tests detected|\d+ failed tests? detected)\s*$")
_MAX_LINE_CHARS = 300
_MAX_DETAILS_CHARS = 800


def _trim(text: str | None, limit: int) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[:limit] + f"… [+{len(text) - limit} chars]"


def find_error_lines(lines: list[str], max_matches: int, context: int) -> tuple[list[dict[str, Any]], int]:
    """Pick the log lines most likely to explain a failure.

    Lines TeamCity marked as errors or warnings come first, then unmarked
    lines with error keywords. Returns compact excerpts and the total number
    of candidate lines.
    """
    # Skip the summary header TeamCity prepends (lines before the first timestamp).
    first = next((i for i, line in enumerate(lines) if _TIMESTAMPED_RE.match(line)), len(lines))
    marked: list[int] = []
    keyword: list[int] = []
    for i in range(first, len(lines)):
        line = lines[i]
        if "##teamcity[" in line:
            continue
        if _MARKED_RE.match(line):
            if not _BLOCK_HEADER_RE.match(line) and not _TEST_SUMMARY_RE.search(line):
                marked.append(i)
        elif _TIMESTAMPED_RE.match(line) and _KEYWORD_RE.search(line):
            # Untimestamped lines are continuations, e.g. the echoed source of a
            # script step; they show up as context, never as matches.
            keyword.append(i)

    chosen = sorted((marked + keyword)[:max_matches]) if len(marked) < max_matches else sorted(marked[:max_matches])
    excerpts: list[dict[str, Any]] = []
    covered = -1
    for idx in chosen:
        start = max(first, idx - context, covered + 1)
        end = min(len(lines), idx + context + 1)
        if excerpts and start <= covered + 1 and excerpts[-1]["end_line"] >= start - 1:
            # Merge with the previous excerpt when they touch.
            prev = excerpts[-1]
            prev["lines"].extend(f"{j}: {_trim(lines[j], _MAX_LINE_CHARS)}" for j in range(prev["end_line"] + 1, end))
            prev["end_line"] = max(prev["end_line"], end - 1)
            prev["match_lines"].append(idx)
        else:
            excerpts.append(
                {
                    "match_lines": [idx],
                    "end_line": end - 1,
                    "lines": [f"{j}: {_trim(lines[j], _MAX_LINE_CHARS)}" for j in range(start, end)],
                }
            )
        covered = max(covered, end - 1)
    for e in excerpts:
        e.pop("end_line")
    return excerpts, len(marked) + len(keyword)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def diagnose_build(
        ctx: Context,
        build_id: Annotated[str, "Numeric build ID"],
        max_failed_tests: Annotated[int, Field(description="Failed tests to include", ge=0, le=50)] = 10,
        max_log_matches: Annotated[int, Field(description="Error log lines to include", ge=0, le=50)] = 12,
        context_lines: Annotated[int, Field(description="Log lines of context around each match", ge=0, le=10)] = 2,
    ) -> dict[str, Any]:
        """Explain why a build failed, in one call.

        Combines the build's status, its build problems, its failed tests
        (unmuted first, with failure details) and the log lines most likely to
        explain the failure: lines TeamCity marked as errors plus lines with
        error keywords, with a little context. Use this first for "why did
        build X fail?"; drill down with get_build_log, search_build_log or
        get_test_details afterwards.

        Example questions:
            - "Why did build 12345 fail?"
            - "What broke the nightly build?"
        """
        try:
            build_id = v.build_id(build_id)
        except v.InvalidArgument as exc:
            return v.invalid(exc)

        app = ctx.lifespan_context
        client = app.client

        try:
            build = await client.get(
                f"/app/rest/builds/id:{build_id}",
                params={
                    "fields": (
                        "id,number,status,state,statusText,branchName,webUrl,"
                        "buildType(id,name,projectName),"
                        "snapshot-dependencies(build(id,number,status,buildType(id,name))),"
                        "testOccurrences(count,passed,failed,muted,newFailed)"
                    )
                },
            )
            if not isinstance(build, dict):
                return {"error": f"Unexpected response for build '{build_id}'"}

            bt = build.get("buildType") or {}
            tests_summary = build.get("testOccurrences") or {}
            result: dict[str, Any] = {
                "build_id": build_id,
                "number": build.get("number"),
                "status": build.get("status"),
                "state": build.get("state"),
                "status_text": build.get("statusText"),
                "branch_name": build.get("branchName"),
                "build_type": f"{bt.get('projectName')} / {bt.get('name')}" if bt else None,
                "build_type_id": bt.get("id"),
                "web_url": build.get("webUrl"),
            }

            deps = (build.get("snapshot-dependencies") or {}).get("build", [])
            failed_deps = [
                {
                    "build_id": d.get("id"),
                    "status": d.get("status"),
                    "build_type_id": (d.get("buildType") or {}).get("id"),
                }
                for d in deps
                if d.get("status") not in (None, "SUCCESS")
            ]
            if failed_deps:
                result["failed_dependencies"] = failed_deps

            problems = await client.get(
                "/app/rest/problemOccurrences",
                params={
                    "locator": f"build:(id:{build_id}),count:50",
                    "fields": "problemOccurrence(type,identity,details,muted)",
                },
            )
            result["problems"] = [
                {"type": p.get("type"), "details": _trim(p.get("details"), _MAX_DETAILS_CHARS), "muted": p.get("muted")}
                for p in (problems.get("problemOccurrence", []) if isinstance(problems, dict) else [])
            ]

            if tests_summary.get("failed") and max_failed_tests:
                occ = await client.get(
                    "/app/rest/testOccurrences",
                    params={
                        "locator": f"build:(id:{build_id}),status:FAILURE,count:200",
                        "fields": "testOccurrence(id,name,details,muted,currentlyMuted,newFailure)",
                    },
                )
                failed = occ.get("testOccurrence", []) if isinstance(occ, dict) else []
                failed.sort(key=lambda t: (bool(t.get("muted") or t.get("currentlyMuted")), not t.get("newFailure")))
                result["failed_tests"] = [
                    {
                        "id": t.get("id"),
                        "name": t.get("name"),
                        "new_failure": bool(t.get("newFailure")),
                        "muted": bool(t.get("muted") or t.get("currentlyMuted")),
                        "details": _trim(t.get("details"), _MAX_DETAILS_CHARS),
                    }
                    for t in failed[:max_failed_tests]
                ]
                result["test_counts"] = {
                    k: tests_summary.get(k) for k in ("count", "passed", "failed", "muted", "newFailed")
                }

            failed_or_running = build.get("status") != "SUCCESS" or build.get("state") != "finished"
            if max_log_matches and failed_or_running:
                build_log = await app.log_cache.get(client, build_id)
                excerpts, candidates = find_error_lines(build_log.lines, max_log_matches, context_lines)
                result["log_excerpts"] = excerpts
                result["log"] = {
                    "total_lines": len(build_log.lines),
                    "error_candidates": candidates,
                    "build_finished": build_log.finished,
                }

            if build.get("state") != "finished":
                result["note"] = f"The build is {build.get('state')}; problems and log lines so far only."
            elif build.get("status") == "SUCCESS" and not result["problems"]:
                result["note"] = "The build has no problems recorded; nothing to diagnose."

            logger.info("diagnose_build build_id=%s status=%s", build_id, build.get("status"))
            return result

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return not_found("Build", build_id)
            return api_error(exc)
        except httpx.RequestError as exc:
            return connection_error(exc)
