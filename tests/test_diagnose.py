"""Tests for the diagnose_build tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from helpers import extract_tools

from mcp_teamcity.tools import diagnose
from mcp_teamcity.tools.diagnose import find_error_lines

LOG = """Build 'Proj / Nightly' #1
Finished with status FAILURE 'OutOfMemoryError found'

[10:00:00]E: bt4 (10s)
[10:00:00]E: Step 1/1: run (Command Line)
echo "error: this is the script source"
[10:00:01] :\t [Step 1/1] batch 1 ok
[10:00:01] :\t [Step 1/1] batch 2 ok
[10:00:02] :\t [Step 1/1] Exception in thread "main" java.lang.OutOfMemoryError: Java heap space
\tat com.example.Report.aggregate(Report.java:211)
[10:00:03] :\t [Step 1/1] batch 3 ok
[10:00:03] :\t [Step 1/1] ##teamcity[buildProblem description='error']
[10:00:04]E:\t [Step 1/1] Failed tests detected
[10:00:04]E:\t [Step 1/1] Process exited with code 1 (Step: run (Command Line))
[10:00:05] : Publishing artifacts
[10:00:06]E: 1 failed test detected
[10:00:06] : Build finished"""


def test_find_error_lines_picks_explanatory_lines() -> None:
    lines = LOG.splitlines()
    excerpts, candidates = find_error_lines(lines, max_matches=10, context=1)
    matched = [lines[i] for e in excerpts for i in e["match_lines"]]
    assert any("OutOfMemoryError" in m for m in matched)
    assert any("Process exited with code 1" in m for m in matched)
    # Header, block openers, script source, service messages and test summaries are skipped.
    assert not any("bt4" in m or "Step 1/1: run" in m for m in matched)
    assert not any("script source" in m for m in matched)
    assert not any("##teamcity" in m for m in matched)
    assert not any("failed test" in m.lower() for m in matched)
    assert candidates == 2
    # Context keeps the stack-trace continuation line.
    assert any("Report.java:211" in line for e in excerpts for line in e["lines"])


def test_find_error_lines_caps_matches_and_prefers_marked_lines() -> None:
    lines = [f"[10:00:{i:02d}]E:\t [Step 1/1] failure {i}" for i in range(30)]
    lines += ["[10:01:00] :\t error in plain output"]
    excerpts, candidates = find_error_lines(lines, max_matches=5, context=0)
    matched = [i for e in excerpts for i in e["match_lines"]]
    assert len(matched) == 5
    assert candidates == 31
    assert 30 not in matched


def _ctx(mock_ctx: MagicMock, build: dict, problems: list, tests: list, log: str) -> MagicMock:
    async def fake_get(path, params=None):
        if path.startswith("/app/rest/builds/id:"):
            return build if params["fields"] != "state" else {"state": build.get("state", "finished")}
        if path == "/app/rest/problemOccurrences":
            return {"problemOccurrence": problems}
        if path == "/app/rest/testOccurrences":
            return {"testOccurrence": tests}
        raise AssertionError(path)

    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(side_effect=fake_get)
    client.get_text = AsyncMock(return_value=log)
    return client


async def test_diagnose_failed_build(mock_ctx: MagicMock) -> None:
    build = {
        "id": 6,
        "status": "FAILURE",
        "state": "finished",
        "statusText": "Tests failed: 2",
        "buildType": {"id": "P_N", "name": "Nightly", "projectName": "Proj"},
        "testOccurrences": {"count": 3, "failed": 2, "muted": 1},
        "snapshot-dependencies": {"build": [{"id": 5, "status": "FAILURE", "buildType": {"id": "P_B"}}]},
    }
    problems = [{"type": "TC_EXIT_CODE", "details": "Process exited with code 1"}]
    tests = [
        {"id": "build:(id:6),id:1", "name": "muted one", "muted": True, "details": "x" * 2000},
        {"id": "build:(id:6),id:2", "name": "real one", "newFailure": True, "details": "AssertionError"},
    ]
    _ctx(mock_ctx, build, problems, tests, LOG)
    result = await extract_tools(diagnose)["diagnose_build"](mock_ctx, build_id="6")

    assert result["status"] == "FAILURE"
    assert result["build_type"] == "Proj / Nightly"
    assert result["problems"][0]["type"] == "TC_EXIT_CODE"
    assert [t["name"] for t in result["failed_tests"]] == ["real one", "muted one"]
    assert len(result["failed_tests"][1]["details"]) < 1000
    assert result["failed_dependencies"] == [{"build_id": 5, "status": "FAILURE", "build_type_id": "P_B"}]
    assert result["log_excerpts"]
    assert result["log"]["build_finished"] is True


async def test_diagnose_successful_build_skips_the_log(mock_ctx: MagicMock) -> None:
    build = {"id": 1, "status": "SUCCESS", "state": "finished", "buildType": {"id": "P_B"}}
    client = _ctx(mock_ctx, build, [], [], LOG)
    result = await extract_tools(diagnose)["diagnose_build"](mock_ctx, build_id="1")
    assert "nothing to diagnose" in result["note"]
    assert "log_excerpts" not in result
    client.get_text.assert_not_called()


async def test_diagnose_rejects_bad_id(mock_ctx: MagicMock) -> None:
    result = await extract_tools(diagnose)["diagnose_build"](mock_ctx, build_id="6/../x")
    assert result["error"] == "Invalid argument"
