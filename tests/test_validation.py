"""Tests for argument validation and locator escaping."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest
from helpers import extract_tools

from mcp_teamcity import validation as v
from mcp_teamcity.tools import artifacts, build_logs, builds, changes, problems, projects, tests


@pytest.mark.parametrize("value", ["12345", 7, " 42 "])
def test_build_id_accepts_numbers(value) -> None:
    assert v.build_id(value) == str(value).strip()


@pytest.mark.parametrize("value", ["", "12a", "1/../2", "id:1", "1,count:999", "-1", "1" * 20])
def test_build_id_rejects_non_numbers(value) -> None:
    with pytest.raises(v.InvalidArgument):
        v.build_id(value)


@pytest.mark.parametrize("value", ["MyProject", "MyProject_Build", "_Root", "A1"])
def test_external_id_accepts_teamcity_ids(value) -> None:
    assert v.external_id(value, "project_id") == value


@pytest.mark.parametrize("value", ["", "My Project", "Proj),count:(1000", "a/b", "../x", "1abc", "x" * 226])
def test_external_id_rejects_other_text(value) -> None:
    with pytest.raises(v.InvalidArgument):
        v.external_id(value, "project_id")


def test_status_is_normalized_and_checked() -> None:
    assert v.status("failure") == "FAILURE"
    with pytest.raises(v.InvalidArgument):
        v.status("FAILURE,count:1000")


def test_date_format() -> None:
    assert v.date("20240101T000000+0000", "since_date") == "20240101T000000+0000"
    with pytest.raises(v.InvalidArgument):
        v.date("2024-01-01", "since_date")


def test_locator_value_passes_plain_text() -> None:
    assert v.locator_value("release/2.0") == "release/2.0"
    assert v.locator_value("bob") == "bob"


@pytest.mark.parametrize("value", ["x),count:1000,(", "a:b", "name,with,commas", "$base64:abc", "feat(x)", ""])
def test_locator_value_base64_encodes_special_text(value) -> None:
    out = v.locator_value(value)
    assert out.startswith("$base64:")
    payload = out.removeprefix("$base64:")
    assert not any(ch in payload for ch in ",:()$")
    padded = payload + "=" * (-len(payload) % 4)
    assert base64.b64decode(padded).decode() == value


@pytest.mark.parametrize("value", ["reports/junit.xml", "/reports/", "a b/c.txt", ""])
def test_artifact_path_accepts_relative_paths(value) -> None:
    assert v.artifact_path(value) == value.strip().strip("/")


@pytest.mark.parametrize("value", ["../secret", "reports/../../x", "a/./b", "..", "a\\b", "a\nb"])
def test_artifact_path_rejects_traversal(value) -> None:
    with pytest.raises(v.InvalidArgument):
        v.artifact_path(value)


def test_test_occurrence_id() -> None:
    assert v.test_occurrence_id("build:(id:9),id:2000000002")
    assert v.test_occurrence_id("id:-5,build:(id:9)")
    with pytest.raises(v.InvalidArgument):
        v.test_occurrence_id("build:(id:9),id:1/../../server")


# --- tools reject bad input before any request is made ------------------------


@pytest.mark.parametrize(
    ("module", "tool", "kwargs"),
    [
        (builds, "get_build_details", {"build_id": "1/../../server"}),
        (builds, "get_build_statistics", {"build_id": "abc"}),
        (builds, "get_build_chain", {"build_id": "1),count:(9"}),
        (builds, "search_builds", {"build_type_id": "X),count:(1000"}),
        (builds, "search_builds", {"project_id": "P", "status": "FAILURE,count:1"}),
        (builds, "search_builds", {"project_id": "P", "since_date": "yesterday"}),
        (build_logs, "get_build_log", {"build_id": "x"}),
        (build_logs, "search_build_log", {"build_id": "x", "query": "e"}),
        (tests, "get_build_test_results", {"build_id": "1;"}),
        (tests, "get_test_details", {"test_locator": "../../server"}),
        (artifacts, "list_build_artifacts", {"build_id": "1", "path": "../../../app/rest/server"}),
        (artifacts, "get_build_artifact_content", {"build_id": "1", "path": "a/../../b"}),
        (problems, "get_build_problems", {"build_id": "-1"}),
        (problems, "search_investigations", {"project_id": "a b"}),
        (problems, "list_muted_tests", {"build_type_id": "a:b"}),
        (projects, "get_project_details", {"project_id": "P/../x"}),
        (changes, "get_change_details", {"change_id": "1,2"}),
        (changes, "search_changes", {"build_id": "abc"}),
    ],
)
async def test_tools_reject_invalid_arguments(mock_ctx: MagicMock, module, tool, kwargs) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock()
    client.get_text = AsyncMock()
    result = await extract_tools(module)[tool](mock_ctx, **kwargs)
    assert result["error"] == "Invalid argument"
    client.get.assert_not_called()
    client.get_text.assert_not_called()


async def test_free_text_is_escaped_in_locators(mock_ctx: MagicMock) -> None:
    client = mock_ctx.lifespan_context.client
    client.get = AsyncMock(return_value={"count": 0})
    await extract_tools(builds)["search_builds"](mock_ctx, project_id="P", branch="x),count:1000,(")
    locator = client.get.await_args.kwargs["params"]["locator"]
    assert "count:1000" not in locator
    assert "branch:(name:(value:$base64:" in locator

    await extract_tools(changes)["search_changes"](mock_ctx, project_id="P", username="a),build:(id:1")
    assert "build:(id:1" not in client.get.await_args.kwargs["params"]["locator"]

    await extract_tools(problems)["search_investigations"](mock_ctx, assignee="x),count:(1")
    assert "count:(1" not in client.get.await_args.kwargs["params"]["locator"]
